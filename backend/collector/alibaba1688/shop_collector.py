from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from collector.alibaba1688.cdp_cookies import alibaba_cdp_enabled, _cdp_url
from collector.alibaba1688.url_parser import Alibaba1688UrlParser, Alibaba1688UrlType

logger = logging.getLogger(__name__)


@dataclass
class Alibaba1688Offer:
    offer_id: str
    title: str | None = None
    price_text: str | None = None
    source_url: str | None = None
    main_image_url: str | None = None
    images: list[str] = field(default_factory=list)
    shop_name: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    skus: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class Alibaba1688ShopCollector:
    """通过本机调试 Chrome（CDP）采集 1688 整店商品列表 + 详情。"""

    def __init__(self, *, delay_ms: int | None = None, timeout_ms: int | None = None) -> None:
        self.delay_ms = delay_ms if delay_ms is not None else int(os.getenv("1688_SHOP_DELAY_MS", "800"))
        self.timeout_ms = timeout_ms if timeout_ms is not None else int(
            os.getenv("1688_SHOP_TIMEOUT_MS", "60000")
        )

    def collect_shop(self, shop_url: str, *, top_n: int = 50) -> list[Alibaba1688Offer]:
        limit = max(1, min(int(top_n), 200))
        parsed = Alibaba1688UrlParser().parse(shop_url)
        if parsed.type is not Alibaba1688UrlType.SHOP:
            raise ValueError("请粘贴 1688 店铺链接，而不是单品链接")
        if not alibaba_cdp_enabled():
            raise RuntimeError("未开启 1688 CDP（1688_USE_CDP），无法采集店铺")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("未安装 playwright，无法从 Chrome 采集 1688 店铺") from exc

        cdp = _cdp_url()
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(cdp)
            except Exception as exc:
                raise RuntimeError(
                    f"无法接入 Chrome CDP（{cdp}）。请先运行 start-ozon-chrome.ps1，"
                    "并在调试 Chrome 登录 1688"
                ) from exc

            try:
                if not browser.contexts:
                    raise RuntimeError("已连接 Chrome，但没有任何上下文")
                context = browser.contexts[0]
                page = context.new_page()
                try:
                    offer_refs = self._collect_offer_refs(page, parsed.source_url, limit)
                    if not offer_refs:
                        raise RuntimeError(
                            "店铺页未找到商品链接。请确认链接可打开、已登录 1688，"
                            "或店铺需要先在调试 Chrome 里手动打开一次"
                        )
                    offers: list[Alibaba1688Offer] = []
                    for index, ref in enumerate(offer_refs[:limit]):
                        detail = self._fetch_offer_detail(page, ref)
                        detail.raw_payload = {
                            **(detail.raw_payload or {}),
                            "shop_url": parsed.source_url,
                            "sales_rank": index + 1,
                        }
                        offers.append(detail)
                        self._sleep()
                    return offers
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    def _sleep(self) -> None:
        time.sleep(max(0, self.delay_ms) / 1000.0)

    @staticmethod
    def _abs_cbu_image(uri: str | None) -> str:
        text = str(uri or "").strip()
        if not text:
            return ""
        if text.startswith("http"):
            return text
        return f"https://cbu01.alicdn.com/{text.lstrip('/')}"

    def _ingest_offer_list_payload(self, payload: Any, seen: dict[str, dict[str, str]]) -> int:
        """从 ModuleAsyncService 的 offerList 写入 seen，返回新增条数。"""
        if not isinstance(payload, dict):
            return 0
        content = (payload.get("data") or {}).get("content") if isinstance(payload.get("data"), dict) else None
        if not isinstance(content, dict):
            return 0
        offer_list = content.get("offerList")
        if not isinstance(offer_list, list):
            return 0
        added = 0
        for item in offer_list:
            if not isinstance(item, dict):
                continue
            oid = str(item.get("id") or "").strip()
            if not re.fullmatch(r"\d{8,}", oid) or oid in seen:
                continue
            title = str(item.get("subject") or "").strip()
            price = item.get("offerPrice")
            if price is None or str(price) in {"", "0", "0.0"}:
                price = item.get("originalPrice")
            price_text = f"¥{price}" if price not in (None, "") else ""
            image = ""
            image_list: list[str] = []
            images = item.get("offerImages")
            if isinstance(images, list):
                for img in images[:12]:
                    if not isinstance(img, dict):
                        continue
                    uri = self._abs_cbu_image(
                        img.get("size310x310ImageURI")
                        or img.get("imageURI")
                        or img.get("summImageURI")
                    )
                    if uri and uri not in image_list:
                        image_list.append(uri)
                if image_list:
                    image = image_list[0]
            seen[oid] = {
                "offer_id": oid,
                "url": f"https://detail.1688.com/offer/{oid}.html",
                "title": title[:200],
                "image": image,
                "images": ",".join(image_list[:12]),
                "price": price_text,
            }
            added += 1
        return added

    def _collect_offer_refs(self, page: Any, shop_url: str, limit: int) -> list[dict[str, str]]:
        """
        新版店铺「全部商品」页 DOM 无 detail.1688 链接，商品在
        mtop.alibaba.alisite.cbu.server.ModuleAsyncService 的 offerList 里。
        """
        seen: dict[str, dict[str, str]] = {}

        def on_response(resp: Any) -> None:
            try:
                url = str(getattr(resp, "url", "") or "")
                if "moduleasyncservice" not in url.lower():
                    return
                body = resp.text()
                if not body or len(body) < 500:
                    return
                match = re.match(r"^\s*[\w$]+\((.*)\)\s*;?\s*$", body, re.S)
                text = match.group(1) if match else body
                payload = json.loads(text)
                self._ingest_offer_list_payload(payload, seen)
            except Exception as exc:
                logger.debug("parse shop ModuleAsyncService failed: %s", exc)

        page.on("response", on_response)
        try:
            page.goto(shop_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(3500)

            stagnant_rounds = 0
            for _ in range(25):
                before = len(seen)
                if len(seen) >= limit:
                    break
                # 兜底：少数店铺仍有 a[href*="offer"]
                batch = page.evaluate(
                    """() => {
                      const out = [];
                      const re = /(?:detail\\.1688\\.com\\/offer\\/|offer\\/)(\\d{8,})/i;
                      for (const a of Array.from(document.querySelectorAll('a[href*="offer"]'))) {
                        const href = a.href || a.getAttribute('href') || '';
                        const m = href.match(re);
                        if (!m) continue;
                        const card = a.closest('[class*="offer"],[class*="card"],[class*="item"],li,div') || a;
                        const img = card.querySelector('img');
                        out.push({
                          offer_id: m[1],
                          url: href.startsWith('http') ? href.split('?')[0] : '',
                          title: (a.getAttribute('title') || a.innerText || '').replace(/\\s+/g,' ').trim().slice(0,200),
                          image: img && (img.src || img.getAttribute('data-src') || '') || '',
                          price: '',
                        });
                      }
                      return out;
                    }"""
                )
                for item in batch or []:
                    if not isinstance(item, dict):
                        continue
                    oid = str(item.get("offer_id") or "").strip()
                    if not oid or oid in seen:
                        continue
                    seen[oid] = {
                        "offer_id": oid,
                        "url": str(item.get("url") or f"https://detail.1688.com/offer/{oid}.html"),
                        "title": str(item.get("title") or ""),
                        "image": str(item.get("image") or ""),
                        "price": str(item.get("price") or ""),
                    }

                if len(seen) >= limit:
                    break
                if len(seen) == before:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                if stagnant_rounds >= 2:
                    clicked = False
                    for selector in (
                        'a:has-text("下一页")',
                        'button:has-text("下一页")',
                        '[class*="next"]:not([disabled])',
                        'a[aria-label="下一页"]',
                    ):
                        try:
                            loc = page.locator(selector).first
                            if loc.count() and loc.is_visible():
                                loc.click(timeout=2000)
                                page.wait_for_timeout(2500)
                                clicked = True
                                stagnant_rounds = 0
                                break
                        except Exception:
                            continue
                    if not clicked:
                        break
                else:
                    page.evaluate("window.scrollBy(0, Math.max(600, window.innerHeight * 0.9))")
                    page.wait_for_timeout(900)
        finally:
            try:
                page.remove_listener("response", on_response)
            except Exception:
                pass

        return list(seen.values())[:limit]

    def _fetch_offer_detail(self, page: Any, ref: dict[str, str]) -> Alibaba1688Offer:
        offer_id = ref["offer_id"]
        url = ref.get("url") or f"https://detail.1688.com/offer/{offer_id}.html"
        sku_payloads: list[dict[str, Any]] = []

        def on_sku_response(resp: Any) -> None:
            try:
                resp_url = str(getattr(resp, "url", "") or "")
                if "queryofferskuselectormodel" not in resp_url.lower():
                    return
                body = resp.text()
                if not body or len(body) < 200:
                    return
                match = re.match(r"^\s*[\w$]+\((.*)\)\s*;?\s*$", body, re.S)
                text = match.group(1) if match else body
                payload = json.loads(text)
                if isinstance(payload, dict):
                    sku_payloads.append(payload)
            except Exception as exc:
                logger.debug("parse sku selector failed offer_id=%s: %s", offer_id, exc)

        page.on("response", on_sku_response)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            page.wait_for_timeout(2800)
            # 点开「包装信息」再读表格（详情默认可能在商品详情 tab）
            page.evaluate(
                """() => {
                  const nodes = Array.from(document.querySelectorAll('div,span,li,a,button'));
                  for (const el of nodes) {
                    const t = (el.innerText || '').trim();
                    if (t === '包装信息' || t === '包装') { el.click(); return true; }
                  }
                  return false;
                }"""
            )
            page.wait_for_timeout(1200)
            data = page.evaluate(_DETAIL_EXTRACT_JS) or {}
        except Exception as exc:
            logger.warning("1688 offer detail failed offer_id=%s: %s", offer_id, exc)
            data = {}
        finally:
            try:
                page.remove_listener("response", on_sku_response)
            except Exception:
                pass

        if not isinstance(data, dict):
            data = {}
        # 标题：document.title 最准；h1 常是店名
        title = str(ref.get("title") or "").strip() or None
        page_title = str(data.get("title") or "").strip()
        if page_title and page_title not in {"", "阿里巴巴"} and "公司" not in page_title[-6:]:
            title = page_title
        elif page_title and not title:
            title = page_title

        # 价格：列表接口价更干净（¥10.98）；SKU 级价格在 skus 里
        price_text = str(ref.get("price") or "").strip() or None
        if not price_text:
            raw_price = str(data.get("price_text") or "").strip()
            m = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", raw_price.replace(" ", ""))
            if not m:
                m = re.search(r"(\d+(?:\.\d+)?)", raw_price.replace(" ", ""))
            if m:
                price_text = f"¥{m.group(1)}"

        images = [str(u).strip() for u in (data.get("images") or []) if str(u).strip()]
        list_images = [
            u.strip()
            for u in str(ref.get("images") or "").split(",")
            if u.strip()
        ]
        # 列表 offerImages + 详情图库；不要把全页装饰图灌进来
        from collector.alibaba1688.image_filter import filter_1688_product_images

        prefer = [str(ref.get("image") or "").strip()] + list_images
        images = filter_1688_product_images(
            [*prefer, *images, *list_images],
            max_count=12,
            prefer=prefer,
        )
        if not images and ref.get("image"):
            images = filter_1688_product_images([ref["image"]], max_count=12)

        pack_rows = data.get("pack_rows") if isinstance(data.get("pack_rows"), list) else []

        from collector.alibaba1688.sku_parse import merge_pack_into_skus, parse_sku_selector_payload

        selector_skus: list[dict[str, Any]] = []
        for payload in sku_payloads:
            parsed = parse_sku_selector_payload(payload)
            if parsed:
                selector_skus = parsed
                break
        # SKU 选择器优先（含各规格价/图），再合并包装表尺寸重量
        skus = merge_pack_into_skus(selector_skus, pack_rows)
        # 丢掉完全空的行；有组合名/skuId 的双轴 SKU 必须保留
        skus = [
            item
            for item in skus
            if isinstance(item, dict)
            and (
                item.get("price_text")
                or item.get("weight_g")
                or item.get("length_cm")
                or item.get("image_url")
                or item.get("sku_id")
                or item.get("label")
                or item.get("color")
            )
        ]
        if not skus and pack_rows:
            skus = [
                {
                    "label": str(row.get("color") or row.get("spec") or f"SKU{i + 1}"),
                    "color": row.get("color"),
                    "spec": row.get("spec"),
                    "length_cm": row.get("length_cm"),
                    "width_cm": row.get("width_cm"),
                    "height_cm": row.get("height_cm"),
                    "weight_g": row.get("weight_g"),
                    "volume_cm3": row.get("volume_cm3"),
                }
                for i, row in enumerate(pack_rows)
                if isinstance(row, dict)
            ][:80]

        # 主图：优先第一个有图的 SKU；不要把所有颜色 SKU 图塞进商品图库
        # （各颜色图属于各自 listing，在 _build_variants 里写入）
        first_sku_img = ""
        for sku in skus:
            img = str(sku.get("image_url") or "").strip()
            if img:
                first_sku_img = img
                break
        images = filter_1688_product_images(
            images,
            max_count=12,
            prefer=[first_sku_img, str(ref.get("image") or "").strip(), *list_images],
        )
        main = images[0] if images else (first_sku_img or ref.get("image") or None)

        from services.ozon_pricing_service import parse_cny_price

        sku_prices = []
        for sku in skus:
            amount = parse_cny_price(sku.get("price_text"))
            if amount:
                sku_prices.append(amount)
        if sku_prices:
            low, high = min(sku_prices), max(sku_prices)
            price_text = f"¥{low}" if abs(low - high) < 1e-6 else f"¥{low}-¥{high}"

        attrs = dict(data.get("attributes") if isinstance(data.get("attributes"), dict) else {})
        if pack_rows:
            attrs["pack_rows"] = pack_rows
        shop_name = str(data.get("shop_name") or "").strip() or None

        from collector.alibaba1688.package_parse import extract_package_metrics

        package_metrics = extract_package_metrics(attributes=attrs, detail={**data, "pack_rows": pack_rows})
        if package_metrics.get("depth_mm"):
            attrs["depth_mm"] = str(package_metrics["depth_mm"])
            attrs["width_mm"] = str(package_metrics["width_mm"])
            attrs["height_mm"] = str(package_metrics["height_mm"])
            attrs["Длина, мм"] = str(package_metrics["depth_mm"])
            attrs["Ширина, мм"] = str(package_metrics["width_mm"])
            attrs["Высота, мм"] = str(package_metrics["height_mm"])
            attrs["Размеры, мм"] = (
                f"{package_metrics['depth_mm']}*{package_metrics['width_mm']}*{package_metrics['height_mm']}"
            )
        if package_metrics.get("weight_g"):
            attrs["weight_g"] = str(package_metrics["weight_g"])
            attrs["weight"] = str(package_metrics["weight_g"])
            attrs["Вес, г"] = str(package_metrics["weight_g"])
            attrs["Вес товара, г"] = str(package_metrics["weight_g"])
            attrs["Вес с упаковкой, г"] = str(package_metrics["weight_g"])
        if package_metrics:
            attrs["package_manual"] = "1"
            attrs["package_source"] = "1688_detail"

        return Alibaba1688Offer(
            offer_id=offer_id,
            title=title,
            price_text=price_text,
            source_url=url,
            main_image_url=main,
            images=images[:12],
            shop_name=shop_name,
            attributes=attrs,
            skus=[item for item in skus if isinstance(item, dict)][:80],
            raw_payload={
                "list_ref": ref,
                "detail": data,
                "package_metrics": package_metrics,
                "pack_rows": pack_rows,
                "sku_selector": sku_payloads[0] if sku_payloads else None,
                "page_host": urlparse(url).hostname,
            },
        )


_DETAIL_EXTRACT_JS = """() => {
  const abs = (u) => {
    if (!u) return '';
    try { return new URL(u, location.href).href; } catch (e) { return String(u); }
  };
  const uniq = (arr) => {
    const out = [];
    const seen = new Set();
    for (const x of arr) {
      const v = String(x || '').trim();
      if (!v || seen.has(v)) continue;
      seen.add(v);
      out.push(v);
    }
    return out;
  };

  // 标题：document.title 去掉站点后缀；不要用 h1（常为店名）
  let title = (document.title || '').replace(/\\s*[-|－].*阿里巴巴.*$/i, '').trim();
  if (!title || /公司$/.test(title)) {
    const og = document.querySelector('meta[property="og:title"]')?.content?.trim();
    if (og) title = og.replace(/\\s*[-|－].*阿里巴巴.*$/i, '').trim();
  }

  const pageText = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ');
  const pick = (re) => {
    const m = pageText.match(re);
    return m ? (m[1] || m[0]).trim() : '';
  };

  let priceText =
    pick(/[¥￥]\\s*([0-9]+(?:\\.[0-9]+)?)/)
    || pick(/([0-9]+(?:\\.[0-9]+)?)\\s*元/);
  if (priceText && !/[¥￥]/.test(priceText)) priceText = '¥' + priceText;

  // 只采商品图库，不采详情富文本/全页装饰图（卡通、图标、店招等）
  const absImg = (el) => abs(
    el.getAttribute('data-lazy-src')
    || el.getAttribute('data-src')
    || el.getAttribute('data-original')
    || el.src
    || ''
  );
  const gallerySelectors = [
    '[class*="detail-gallery"]',
    '[class*="DetailGallery"]',
    '[class*="od-gallery"]',
    '[class*="gallery-img"]',
    '[class*="img-list-wrapper"]',
    '[class*="main-image"]',
    '[class*="MainImage"]',
    '[class*="preview-img"]',
    '#dt-tab',
    '.tab-content-container',
    '[class*="v-image"]',
    '[class*="vertical-img"]',
  ].join(',');
  const galleryRoots = Array.from(document.querySelectorAll(gallerySelectors));
  let galleryImgs = [];
  for (const root of galleryRoots) {
    for (const img of Array.from(root.querySelectorAll('img'))) {
      galleryImgs.push(absImg(img));
    }
  }
  const og = document.querySelector('meta[property="og:image"]')?.content?.trim() || '';
  if (og) galleryImgs.unshift(abs(og));

  // 图库为空时，仅取页面上半区（首屏）大图，仍排除详情长图里的装饰
  if (!galleryImgs.length) {
    const vh = Math.max(600, (window.innerHeight || 800) * 1.2);
    for (const img of Array.from(document.querySelectorAll('img'))) {
      try {
        const rect = img.getBoundingClientRect();
        if (rect.top > vh) continue;
        if (rect.width > 0 && rect.width < 80) continue;
        if (rect.height > 0 && rect.height < 80) continue;
      } catch (e) {}
      galleryImgs.push(absImg(img));
      if (galleryImgs.length >= 12) break;
    }
  }

  const images = uniq(galleryImgs).filter((u) =>
    /alicdn|alibaba|1688|cbu\\d+/i.test(u)
    && !/avatar|logo|icon|\\.svg|tps-\\d|emoji|sticker|sprite|qrcode|wangpu|banner|button|btn_|badge|loading|placeholder|\\.gif(?:\\?|$)/i.test(u)
  ).slice(0, 12);

  // 包装信息表：长/宽/高(cm) + 重量(g)
  const pack_rows = [];
  const packTable = document.querySelector('.offer-pack-info-list table')
    || Array.from(document.querySelectorAll('table')).find((tb) => {
      const head = (tb.innerText || '');
      return head.includes('长') && head.includes('宽') && head.includes('重量');
    });
  if (packTable) {
    const headers = Array.from(packTable.querySelectorAll('thead th, tr th')).map((th) =>
      (th.innerText || '').replace(/\\s+/g, '').trim()
    );
    const findIdx = (...names) => {
      for (const n of names) {
        const i = headers.findIndex((h) => h.includes(n));
        if (i >= 0) return i;
      }
      return -1;
    };
    let iColor = findIdx('颜色', '款式', '型号');
    let iSpec = findIdx('规格');
    let iL = findIdx('长');
    let iW = findIdx('宽');
    let iH = findIdx('高(cm)', '高（cm）', '高');
    let iVol = findIdx('体积');
    let iWeight = findIdx('重量');
    // 无 thead 时按常见列序
    if (iL < 0) { iColor = 0; iSpec = 1; iL = 2; iW = 3; iH = 4; iVol = 5; iWeight = 6; }
    const bodyRows = packTable.querySelectorAll('tbody tr');
    const rows = bodyRows.length ? bodyRows : Array.from(packTable.querySelectorAll('tr')).slice(1);
    for (const tr of Array.from(rows)) {
      const cells = Array.from(tr.querySelectorAll('td')).map((td) => (td.innerText || '').replace(/\\s+/g, ' ').trim());
      if (cells.length < 4) continue;
      const num = (v) => {
        const m = String(v || '').match(/([0-9]+(?:\\.[0-9]+)?)/);
        return m ? m[1] : '';
      };
      const length_cm = num(cells[iL]);
      const width_cm = num(cells[iW]);
      const height_cm = num(cells[iH >= 0 ? iH : iL]);
      const weight_g = num(cells[iWeight]);
      if (!length_cm || !width_cm || !weight_g) continue;
      pack_rows.push({
        color: iColor >= 0 ? (cells[iColor] || '') : '',
        spec: iSpec >= 0 ? (cells[iSpec] || '') : '',
        length_cm,
        width_cm,
        height_cm: height_cm || width_cm,
        volume_cm3: iVol >= 0 ? num(cells[iVol]) : '',
        weight_g,
      });
      if (pack_rows.length >= 80) break;
    }
  }

  const attributes = {};
  if (pack_rows.length) {
    attributes['包装尺寸'] = pack_rows[0].length_cm + 'x' + pack_rows[0].width_cm + 'x' + pack_rows[0].height_cm + 'cm';
    attributes['重量'] = pack_rows[0].weight_g + 'g';
  }

  const skus = pack_rows.map((r) => ({
    label: r.color || r.spec || '',
    color: r.color,
    spec: r.spec,
    weight_g: r.weight_g,
    length_cm: r.length_cm,
    width_cm: r.width_cm,
    height_cm: r.height_cm,
  }));
  if (!skus.length) {
    for (const el of Array.from(document.querySelectorAll('[class*="sku"] [class*="item"], [class*="Sku"] [class*="item"], [data-sku]'))) {
      const label = (el.innerText || '').replace(/\\s+/g, ' ').trim();
      if (label && label.length < 60) skus.push({ label });
    }
  }

  const shop =
    document.querySelector('[class*="company"],[class*="shop-name"],[class*="ShopName"]')?.innerText?.trim()
    || '';

  return {
    title: title.slice(0, 300),
    price_text: (priceText || '').slice(0, 64),
    images,
    attributes,
    skus: skus.slice(0, 80),
    pack_rows,
    shop_name: shop.slice(0, 120),
    weight: pack_rows[0] ? (pack_rows[0].weight_g + 'g') : '',
    package: pack_rows[0]
      ? (pack_rows[0].length_cm + 'x' + pack_rows[0].width_cm + 'x' + pack_rows[0].height_cm + 'cm')
      : '',
    volume: '',
    unit_weight: '',
    boot_keys: [],
  };
}"""
