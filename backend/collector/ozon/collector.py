from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

try:
    from curl_cffi import requests as http_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as http_requests  # type: ignore[no-redef]
    HAS_CURL_CFFI = False

from collector.ozon.browser_session import (
    get_ozon_browser_session,
    ozon_browser_enabled,
)
from collector.ozon.models import OzonCollectConfig, OzonCollectionStrategy, OzonProductInfo
from collector.ozon.parser import (
    extract_composer_from_html,
    extract_next_page_path,
    parse_listing_page,
    parse_product_details,
)
from collector.ozon.url_parser import OzonParseResult, OzonUrlParser, OzonUrlType, PRODUCT_IN_JSON

COMPOSER_API_BASES = (
    "https://www.ozon.ru/api/composer-api.bx/page/json/v2",
    "https://api.ozon.ru/composer-api.bx/page/json/v2",
)

ANTIBOT_HINT = (
    "Ozon 反爬拦截。请先运行 start-ozon-chrome.ps1，"
    "在弹出的 Chrome 中打开 ozon.ru 完成验证并保持窗口开着，再重试采集。"
)


def apply_cookie_string(session: Any, cookie_string: str) -> None:
    for part in cookie_string.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        for domain in (".ozon.ru", "www.ozon.ru", "ozon.ru"):
            try:
                session.cookies.set(name, value, domain=domain)
            except Exception:
                continue


class OzonCollector:
    """Ozon collector modeled after AmazonCollector: paste a URL and collect products."""

    def __init__(self, config: OzonCollectConfig | None = None) -> None:
        self.config = config or OzonCollectConfig.defaults()
        self.url_parser = OzonUrlParser()
        self.session = self._build_session()
        self._use_browser = ozon_browser_enabled()
        if self.config.cookie:
            apply_cookie_string(self.session, self.config.cookie)

    def collect(self, url: str, max_products: int | None = None) -> list[OzonProductInfo]:
        parsed = self.url_parser.parse(url)
        self._prepare_session(parsed)
        if parsed.type is OzonUrlType.PRODUCT:
            return [self._collect_product(parsed)]
        return self._collect_from_listing(parsed, max_products=max_products)

    def collect_with_strategy(self, strategy_type: str, strategy_params: dict[str, Any]) -> list[OzonProductInfo]:
        strategy = OzonCollectionStrategy(strategy_type)
        params = dict(strategy_params or {})

        if strategy is OzonCollectionStrategy.PRODUCT_URL:
            url = str(params.get("url") or "").strip()
            if not url:
                raise ValueError("product_url 策略需要提供 url")
            return self.collect(url)

        if strategy is OzonCollectionStrategy.CUSTOM_RULE:
            keyword = str(params.get("keyword") or "").strip()
            if not keyword:
                raise ValueError("custom_rule 策略需要提供 keyword")
            path = f"/search/?text={quote(keyword)}&from_global=true"
            if params.get("sorting"):
                path += f"&sorting={params['sorting']}"
            parsed = OzonParseResult(OzonUrlType.SEARCH, f"https://www.ozon.ru{path}", path)
            self._prepare_session(parsed)
            return self._collect_from_listing(parsed, max_products=int(params.get("top_n") or self.config.max_products))

        category_id = str(params.get("category_id") or "").strip()
        if not category_id:
            raise ValueError("该策略需要提供 category_id")
        sorting = "score"
        if strategy is OzonCollectionStrategy.CATEGORY_LEADERBOARD:
            leaderboard = str(params.get("leaderboard_type") or "top_sales")
            sorting = {
                "top_sales": "score",
                "rating": "rating",
                "new": "new",
                "discount": "discount",
            }.get(leaderboard, "score")
        path = f"/category/{category_id.strip('/')}/?sorting={sorting}"
        parsed = OzonParseResult(OzonUrlType.CATEGORY, f"https://www.ozon.ru{path}", path)
        self._prepare_session(parsed)
        return self._collect_from_listing(parsed, max_products=int(params.get("top_n") or self.config.max_products))

    def _build_session(self) -> Any:
        if HAS_CURL_CFFI:
            return http_requests.Session(impersonate=self.config.impersonate)
        session = http_requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
                ),
            }
        )
        return session

    def _prepare_session(self, parsed: OzonParseResult | None = None) -> None:
        if self._use_browser:
            try:
                get_ozon_browser_session().ensure_started()
                return
            except Exception:
                # 浏览器不可用时回退 HTTP 预热
                pass

        warmup_urls = ["https://www.ozon.ru/"]
        if parsed is not None:
            warmup_urls.append(f"https://www.ozon.ru{parsed.page_path}")

        for index, warmup_url in enumerate(warmup_urls):
            try:
                headers = self._html_headers(referer=warmup_urls[index - 1] if index > 0 else None)
                self.session.get(warmup_url, headers=headers, timeout=self.config.timeout_seconds)
            except Exception:
                continue

    def _collect_product(self, parsed: OzonParseResult) -> OzonProductInfo:
        base_page = self._fetch_page(parsed.page_path)
        details_page = self._fetch_page(
            f"{parsed.page_path}?layout_container=pdpPage2column&layout_page_index=2"
        )
        details = parse_product_details(base_page, details_page)

        product_id = details.get("sku") or parsed.product_id
        if not product_id:
            raise RuntimeError("无法解析 Ozon 商品详情")

        category_id = details.get("description_category_id") or details.get("category_id")
        type_id = details.get("type_id")
        seller_tree: dict[str, Any] | None = None
        try:
            from integrations.ozon_seller.seller_tree import try_resolve_by_sku

            resolved = try_resolve_by_sku(str(product_id))
            if resolved is not None:
                # 卖家后台解析结果优先（比面包屑 categoryId 更准确）
                category_id = resolved.description_category_id
                type_id = resolved.type_id
                details["description_category_id"] = category_id
                details["type_id"] = type_id
                seller_tree = {
                    "description_category_id": category_id,
                    "type_id": type_id,
                    "raw": resolved.raw,
                }
        except Exception:
            seller_tree = None

        raw_payload: dict[str, Any] = {"details": details, "page_path": parsed.page_path}
        if seller_tree is not None:
            raw_payload["seller_tree"] = seller_tree

        return OzonProductInfo(
            product_id=str(product_id),
            title=details.get("name"),
            brand=details.get("brand"),
            price_text=self._format_price(details.get("price")),
            main_image_url=details.get("image"),
            source_url=details.get("url") or parsed.source_url,
            sales_rank=1,
            category_id=category_id,
            type_id=type_id,
            category_name=details.get("category_name"),
            rating=str(details.get("rating") or "") if details.get("rating") is not None else None,
            review_count=str(details.get("reviews") or "") if details.get("reviews") is not None else None,
            variant_attributes=dict(details.get("attributes") or {}),
            raw_payload=raw_payload,
        )

    def _collect_from_listing(self, parsed: OzonParseResult, max_products: int | None = None) -> list[OzonProductInfo]:
        limit = max_products or self.config.max_products
        product_paths = self._discover_product_paths(parsed, limit=limit)
        if not product_paths:
            raise RuntimeError("未在页面中发现商品链接，请检查链接或稍后重试")

        results: list[OzonProductInfo] = []
        for index, product_path in enumerate(product_paths[:limit]):
            try:
                product_parsed = OzonParseResult(
                    OzonUrlType.PRODUCT,
                    f"https://www.ozon.ru{product_path}",
                    product_path,
                    product_id=self.url_parser._extract_product_id(product_path),
                )
                product = self._collect_product(product_parsed)
                product.sales_rank = index + 1
                product.hot_score = float(max(0, 100 - index))
                if parsed.seller_slug:
                    product.raw_payload["seller_slug"] = parsed.seller_slug
                results.append(product)
            except Exception as exc:
                product_id = self.url_parser._extract_product_id(product_path)
                if product_id:
                    results.append(
                        OzonProductInfo(
                            product_id=product_id,
                            source_url=f"https://www.ozon.ru{product_path}",
                            sales_rank=index + 1,
                            raw_payload={"error": str(exc), "page_path": product_path},
                        )
                    )
            if index < min(len(product_paths), limit) - 1:
                self._sleep(self.config.delay_ms)
        return results

    def _discover_product_paths(self, parsed: OzonParseResult, limit: int) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        current_path = parsed.page_path
        if not current_path.endswith("/") and "?" not in current_path:
            current_path += "/"

        for page_index in range(self.config.max_pages):
            page = self._fetch_page(current_path)

            for item in parse_listing_page(page, limit=limit):
                link = item.get("url") or ""
                match = PRODUCT_IN_JSON.search(link)
                if match:
                    path = match.group(0)
                    if not path.startswith("/"):
                        path = f"/{path}"
                    if path not in seen:
                        seen.add(path)
                        paths.append(path)

            for path in PRODUCT_IN_JSON.findall(str(page.get("widgetStates") or page)):
                normalized = path if path.startswith("/") else f"/{path}"
                if normalized not in seen:
                    seen.add(normalized)
                    paths.append(normalized)

            if len(paths) >= limit:
                break

            next_path = extract_next_page_path(page)
            if not next_path or page_index + 1 >= self.config.max_pages:
                break
            current_path = next_path
            self._sleep(self.config.listing_page_delay_ms)

        return paths[:limit]

    def _fetch_page(self, page_path: str) -> dict[str, Any]:
        page_path = page_path if page_path.startswith("/") else f"/{page_path}"
        referer = f"https://www.ozon.ru{page_path.split('?')[0]}"

        if self._use_browser:
            browser_page = self._fetch_via_browser(page_path)
            if browser_page.get("widgetStates"):
                return browser_page

        composer_page = self._fetch_composer_http(page_path, referer=referer)
        if composer_page.get("widgetStates"):
            return composer_page

        html_page = self._fetch_html_page(page_path, referer=referer)
        if html_page is not None:
            return html_page

        if self._use_browser and composer_page:
            return composer_page
        if composer_page:
            return composer_page
        raise RuntimeError(ANTIBOT_HINT)

    def _fetch_via_browser(self, page_path: str) -> dict[str, Any]:
        browser = get_ozon_browser_session()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                payload = browser.fetch_composer(page_path, timeout_seconds=self.config.timeout_seconds)
                if isinstance(payload, dict) and payload.get("widgetStates"):
                    return payload
                last_error = RuntimeError("浏览器返回无 widgetStates")
            except Exception as exc:
                last_error = exc
            if attempt == 0:
                browser.reset()
        if last_error:
            # 再试 HTML 渲染解析
            try:
                html = browser.fetch_html(page_path, timeout_seconds=self.config.timeout_seconds)
                payload = extract_composer_from_html(html)
                if payload and payload.get("widgetStates"):
                    return payload
            except Exception:
                pass
            raise RuntimeError(f"{ANTIBOT_HINT} ({last_error})")
        return {}

    def _fetch_composer_http(self, page_path: str, referer: str) -> dict[str, Any]:
        page_path = page_path if page_path.startswith("/") else f"/{page_path}"
        encoded = quote(page_path, safe="/?=&%")
        headers = {
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer,
            "x-o3-app-name": "dweb_client",
        }
        last_error: Exception | None = None

        for base in COMPOSER_API_BASES:
            url = f"{base}?url={encoded}"
            try:
                response = self.session.get(url, headers=headers, timeout=self.config.timeout_seconds)
                if response.status_code >= 400:
                    last_error = RuntimeError(f"HTTP {response.status_code}")
                    continue
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("composer API 返回格式异常")
                if payload.get("incidentId") and not payload.get("widgetStates"):
                    last_error = RuntimeError("Ozon 返回了反爬拦截页")
                    continue
                return payload
            except Exception as exc:
                last_error = exc
                continue

        if last_error and not self._use_browser:
            raise RuntimeError(f"无法获取 Ozon 页面数据: {last_error}")
        return {}

    def _fetch_html_page(self, page_path: str, referer: str) -> dict[str, Any] | None:
        page_path = page_path if page_path.startswith("/") else f"/{page_path}"
        url = f"https://www.ozon.ru{page_path}"
        try:
            response = self.session.get(
                url,
                headers=self._html_headers(referer=referer),
                timeout=self.config.timeout_seconds,
            )
            if response.status_code >= 400:
                return None
            payload = extract_composer_from_html(response.text)
            if payload and payload.get("widgetStates"):
                return payload
        except Exception:
            return None
        return None

    @staticmethod
    def _html_headers(referer: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
        }
        if referer:
            headers["Referer"] = referer
            headers["Sec-Fetch-Site"] = "same-origin"
        else:
            headers["Sec-Fetch-Site"] = "none"
        return headers

    def _sleep(self, delay_ms: int) -> None:
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)

    @staticmethod
    def _format_price(value: Any) -> str | None:
        if value is None:
            return None
        return f"{value} ₽"
