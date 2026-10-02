"""将开放平台商品详情映射为 Alibaba1688Offer。"""
from __future__ import annotations

import logging
import re
from typing import Any

from collector.alibaba1688.image_filter import filter_1688_product_images
from collector.alibaba1688.open_api import (
    AlibabaOpenApiClient,
    AlibabaOpenApiError,
    is_success_payload,
    needs_relation_or_push,
    open_api_configured,
)
from collector.alibaba1688.package_parse import extract_package_metrics
from collector.alibaba1688.shop_collector import Alibaba1688Offer

logger = logging.getLogger(__name__)


def _dig(obj: Any, *keys: str) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _unwrap_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """兼容多层 result 包裹。"""
    if not isinstance(payload, dict):
        return {}
    candidates: list[Any] = [
        payload,
        payload.get("result"),
        _dig(payload, "result", "result"),
        _dig(payload, "result", "result", "result"),
        payload.get("productInfo"),
        _dig(payload, "result", "productInfo"),
        _dig(payload, "data"),
    ]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        # 真正详情通常带 offerId / subject / productSkuInfos / skuInfos
        if any(
            k in item
            for k in (
                "offerId",
                "productID",
                "productId",
                "subject",
                "productSkuInfos",
                "skuInfos",
                "productImage",
                "imageList",
                "image",
            )
        ):
            return item
        nested = item.get("result") if isinstance(item.get("result"), dict) else None
        if nested and any(
            k in nested for k in ("offerId", "productID", "subject", "productSkuInfos", "skuInfos")
        ):
            return nested
    # 失败信息
    msg = (
        payload.get("error_message")
        or payload.get("message")
        or _dig(payload, "result", "message")
        or _dig(payload, "result", "result", "message")
    )
    success = _dig(payload, "result", "success")
    if success is False or msg:
        raise AlibabaOpenApiError(f"queryProductDetail 失败: {msg or payload}")
    return payload


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_str(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _price_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return f"¥{value}"
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(("¥", "￥")):
        return text.replace("￥", "¥")
    m = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    return f"¥{m.group(1)}" if m else text


def _abs_cbu_image(url: str | None) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return f"https://cbu01.alicdn.com/{text.lstrip('/')}"


def _collect_images(detail: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("imageList", "images", "productImageList"):
        for item in _as_list(detail.get(key)):
            if isinstance(item, str) and item.strip():
                urls.append(_abs_cbu_image(item))
            elif isinstance(item, dict):
                u = _first_str(item.get("imageUrl"), item.get("url"), item.get("originalImageURI"))
                if u:
                    urls.append(_abs_cbu_image(u))
    product_image = detail.get("productImage") or detail.get("image")
    if isinstance(product_image, dict):
        for key in ("images", "imageList", "whiteImageList"):
            for item in _as_list(product_image.get(key)):
                if isinstance(item, str) and item.strip():
                    urls.append(_abs_cbu_image(item))
                elif isinstance(item, dict):
                    u = _first_str(item.get("imageUrl"), item.get("url"))
                    if u:
                        urls.append(_abs_cbu_image(u))
        main = _first_str(product_image.get("imageUrl"), product_image.get("url"))
        if main:
            urls.insert(0, _abs_cbu_image(main))
    elif isinstance(product_image, str) and product_image.strip():
        urls.insert(0, _abs_cbu_image(product_image))
    return filter_1688_product_images(urls, max_count=12)


def _sku_attributes(sku: dict[str, Any]) -> list[dict[str, Any]]:
    raw = sku.get("skuAttributes") or sku.get("skuAttribute") or sku.get("attributes") or []
    if isinstance(raw, dict):
        return [raw]
    return [item for item in _as_list(raw) if isinstance(item, dict)]


def _sku_color_size(attrs: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None, str | None]:
    color = size = label = image = None
    parts: list[str] = []
    for attr in attrs:
        name = _first_str(attr.get("attributeNameTrans"), attr.get("attributeName"), attr.get("name")) or ""
        value = _first_str(attr.get("valueTrans"), attr.get("value"), attr.get("attributeValue")) or ""
        img = _first_str(attr.get("skuImageUrl"), attr.get("imageUrl"), attr.get("skuImage"))
        if img and not image:
            image = img
        if not value:
            continue
        parts.append(value)
        lower = name.lower()
        if re.search(r"色|color|цвет", name, re.I) or re.search(r"色|color", lower):
            color = color or value
        elif re.search(r"尺码|尺寸|规格|size|размер", name, re.I):
            size = size or value
        else:
            # 无明确轴名时：先颜色后尺码启发式
            if color is None and not re.search(r"\d+\s*[x×*]", value, re.I):
                color = value
            elif size is None:
                size = value
    if parts:
        label = " / ".join(parts)
    return color, size, label, image


def _parse_skus(detail: dict[str, Any]) -> list[dict[str, Any]]:
    skus: list[dict[str, Any]] = []
    raw_skus = detail.get("productSkuInfos") or detail.get("skuInfos") or detail.get("productSkuInfoList") or []
    for index, sku in enumerate(_as_list(raw_skus)):
        if not isinstance(sku, dict):
            continue
        attrs = _sku_attributes(sku)
        color, size, label, attr_image = _sku_color_size(attrs)
        price = _price_text(
            sku.get("jxhyPrice")
            or sku.get("price")
            or sku.get("consignPrice")
            or sku.get("retailPrice")
        )
        image = _first_str(attr_image, sku.get("skuImageUrl"), sku.get("imageUrl"))
        if image:
            image = _abs_cbu_image(image)
        weight_g = None
        for key in ("weight", "weightG", "packageWeight", "suttleWeight"):
            raw = sku.get(key)
            if raw is None:
                continue
            try:
                num = float(str(raw).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if num <= 0:
                continue
            # 常见 kg
            weight_g = int(round(num * 1000)) if num < 50 else int(round(num))
            break
        sku_id = _first_str(sku.get("skuId"), sku.get("specId"), sku.get("sku_id"))
        item: dict[str, Any] = {
            "sku_id": sku_id or f"sku-{index + 1}",
            "spec_id": _first_str(sku.get("specId")),
            "label": label or color or size or (sku_id or f"规格{index + 1}"),
            "color": color,
            "size": size,
            "price_text": price,
            "image_url": image,
            "amount_on_sale": sku.get("amountOnSale"),
            "raw": sku,
        }
        if weight_g:
            item["weight_g"] = weight_g
        skus.append(item)
    return skus[:80]


def _parse_attributes(detail: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in _as_list(detail.get("productAttribute") or detail.get("attributes") or []):
        if not isinstance(attr, dict):
            continue
        name = _first_str(attr.get("attributeNameTrans"), attr.get("attributeName"), attr.get("name"))
        value = _first_str(attr.get("valueTrans"), attr.get("value"), attr.get("attributeValue"))
        if name and value:
            out[name] = value
    shipping = detail.get("productShippingInfo") if isinstance(detail.get("productShippingInfo"), dict) else {}
    for key in ("weight", "suttleWeight", "avgWeight", "packageWeight", "volume", "packageSize"):
        if shipping.get(key) not in (None, ""):
            out[key] = shipping.get(key)
    sale = detail.get("productSaleInfo") if isinstance(detail.get("productSaleInfo"), dict) else {}
    if sale.get("priceRangeList"):
        out["priceRangeList"] = sale.get("priceRangeList")
    return out


def map_query_product_detail(
    payload: dict[str, Any],
    *,
    offer_id: str | None = None,
    source: str = "open_api_queryProductDetail",
    relation_meta: dict[str, Any] | None = None,
) -> Alibaba1688Offer:
    detail = _unwrap_detail_payload(payload)
    oid = str(
        offer_id
        or detail.get("offerId")
        or detail.get("productID")
        or detail.get("productId")
        or ""
    ).strip()
    if not oid:
        raise AlibabaOpenApiError(f"详情缺少 offerId: {payload}")

    title = _first_str(detail.get("subjectTrans"), detail.get("subject"), detail.get("title"))
    images = _collect_images(detail)
    skus = _parse_skus(detail)
    attrs = _parse_attributes(detail)

    prices = [_price_text(s.get("price_text")) for s in skus]
    prices = [p for p in prices if p]
    price_text = None
    if prices:
        from services.ozon_pricing_service import parse_cny_price

        nums = [parse_cny_price(p) for p in prices]
        nums = [n for n in nums if n]
        if nums:
            low, high = min(nums), max(nums)
            price_text = f"¥{low}" if abs(low - high) < 1e-6 else f"¥{low}-¥{high}"
    if not price_text:
        sale = detail.get("productSaleInfo") if isinstance(detail.get("productSaleInfo"), dict) else {}
        price_text = _price_text(
            sale.get("price")
            or sale.get("jxhyPrice")
            or detail.get("price")
            or detail.get("referencePrice")
        )

    package_metrics = extract_package_metrics(attributes=attrs, detail=detail)
    if package_metrics.get("depth_mm"):
        attrs["depth_mm"] = str(package_metrics["depth_mm"])
        attrs["width_mm"] = str(package_metrics["width_mm"])
        attrs["height_mm"] = str(package_metrics["height_mm"])
        attrs["Длина, мм"] = str(package_metrics["depth_mm"])
        attrs["Ширина, мм"] = str(package_metrics["width_mm"])
        attrs["Высота, мм"] = str(package_metrics["height_mm"])
    if package_metrics.get("weight_g"):
        attrs["weight_g"] = str(package_metrics["weight_g"])
        attrs["Вес, г"] = str(package_metrics["weight_g"])
        attrs["package_manual"] = "1"
        attrs["package_source"] = "1688_open_api"
    # SKU 缺重量时用商品级重量兜底
    if package_metrics.get("weight_g"):
        for sku in skus:
            if not sku.get("weight_g"):
                sku["weight_g"] = int(package_metrics["weight_g"])

    shop_name = _first_str(
        detail.get("companyName"),
        detail.get("sellerLoginId"),
        _dig(detail, "sellerDataInfo", "companyName"),
    )
    main = images[0] if images else None
    if not main:
        for sku in skus:
            if sku.get("image_url"):
                main = str(sku["image_url"])
                break

    return Alibaba1688Offer(
        offer_id=oid,
        title=title,
        price_text=price_text,
        source_url=f"https://detail.1688.com/offer/{oid}.html",
        main_image_url=main,
        images=images[:12],
        shop_name=shop_name,
        attributes=attrs,
        skus=skus,
        raw_payload={
            "source": source,
            "detail": detail,
            "package_metrics": package_metrics,
            "raw_response": payload,
            "relation": relation_meta or {},
        },
    )


def _try_map_detail(
    payload: dict[str, Any],
    *,
    offer_id: str,
    source: str,
    relation_meta: dict[str, Any] | None = None,
) -> Alibaba1688Offer | None:
    if not isinstance(payload, dict):
        return None
    # 明确失败
    if needs_relation_or_push(payload) and not is_success_payload(payload):
        return None
    try:
        return map_query_product_detail(
            payload,
            offer_id=offer_id,
            source=source,
            relation_meta=relation_meta,
        )
    except AlibabaOpenApiError:
        return None
    except Exception as exc:
        logger.debug("map detail failed offer=%s: %s", offer_id, exc)
        return None


def _map_cross_payload(
    payload: dict[str, Any],
    *,
    offer_id: str,
    relation_meta: dict[str, Any] | None = None,
) -> Alibaba1688Offer | None:
    if isinstance(payload.get("productInfo"), dict):
        wrapped = {"result": payload["productInfo"], "raw_cross": payload, "success": payload.get("success", True)}
        return _try_map_detail(
            wrapped,
            offer_id=offer_id,
            source="open_api_cross_productInfo",
            relation_meta=relation_meta,
        )
    return _try_map_detail(
        payload,
        offer_id=offer_id,
        source="open_api_cross_productInfo",
        relation_meta=relation_meta,
    )


def fetch_offer_via_open_api(
    offer_id: str | int,
    *,
    client: AlibabaOpenApiClient | None = None,
    country: str | None = None,
    ensure_relation: bool = True,
) -> Alibaba1688Offer:
    """
    仅走开放平台（不再回退 CDP）：
    1) queryProductDetail
    2) cross.productInfo
    3) 无权限/不存在 → 幂等关注 + 铺货 → 再查 productInfo
    """
    if not open_api_configured() and client is None:
        raise AlibabaOpenApiError("未配置 1688 开放平台凭证")
    api = client or AlibabaOpenApiClient()
    oid = str(offer_id).strip()
    relation_meta: dict[str, Any] = {"ensured": False}

    # 1) 寻源通详情（池内直出）
    try:
        payload = api.query_product_detail(oid, country=country)
        mapped = _try_map_detail(payload, offer_id=oid, source="open_api_queryProductDetail")
        if mapped is not None:
            return mapped
        logger.info("queryProductDetail 未拿到详情 offer=%s payload=%s", oid, str(payload)[:240])
    except Exception as exc:
        logger.info("queryProductDetail 异常 offer=%s: %s", oid, exc)

    # 2) 跨境详情
    try:
        payload = api.cross_product_info(oid)
        mapped = _map_cross_payload(payload, offer_id=oid)
        if mapped is not None:
            return mapped
        logger.info("cross.productInfo 未拿到详情 offer=%s payload=%s", oid, str(payload)[:240])
        need_push = needs_relation_or_push(payload)
    except Exception as exc:
        logger.info("cross.productInfo 异常 offer=%s: %s", oid, exc)
        need_push = True
        payload = {"error": str(exc)}

    if not ensure_relation or not need_push:
        raise AlibabaOpenApiError(f"无法获取商品详情 offer={oid}: {payload}")

    # 3) 关注 + 铺货（幂等）后再查
    try:
        ensured = api.ensure_offer_relation_and_push(oid)
        relation_meta = {**ensured, "ensured": True}
    except Exception as exc:
        raise AlibabaOpenApiError(f"关注/铺货失败 offer={oid}: {exc}") from exc

    payload = api.cross_product_info(oid)
    mapped = _map_cross_payload(payload, offer_id=oid, relation_meta=relation_meta)
    if mapped is not None:
        return mapped

    # 少数场景铺货后寻源通可读
    try:
        payload2 = api.query_product_detail(oid, country=country)
        mapped2 = _try_map_detail(
            payload2,
            offer_id=oid,
            source="open_api_queryProductDetail_after_push",
            relation_meta=relation_meta,
        )
        if mapped2 is not None:
            return mapped2
    except Exception:
        pass

    push_ok = bool(relation_meta.get("push_ok"))
    hint = (
        "铺货未成功，该商品可能不支持跨境铺货/已下架"
        if not push_ok
        else "铺货已提交但仍无详情权限"
    )
    raise AlibabaOpenApiError(
        f"关注铺货后仍无法获取详情 offer={oid}（{hint}）: {payload}"
    )


def prefetch_relations_for_offers(
    offer_ids: list[str] | list[str | int],
    *,
    client: AlibabaOpenApiClient | None = None,
) -> dict[str, Any]:
    """店铺批量：先幂等关注+铺货（按 20 一批），再逐个拉详情更稳。"""
    api = client or AlibabaOpenApiClient()
    ids = [str(x).strip() for x in offer_ids if str(x).strip().isdigit()]
    # 去重保序
    uniq: list[str] = []
    seen: set[str] = set()
    for oid in ids:
        if oid not in seen:
            seen.add(oid)
            uniq.append(oid)
    related_ok = 0
    related_fail: list[dict[str, str]] = []
    for oid in uniq:
        try:
            api.alibaba1688_cross_border_add_relation(oid)
            related_ok += 1
        except Exception as exc:
            related_fail.append({"offer_id": oid, "error": str(exc)})
    sync = api.alibaba1688_cross_border_sync_product_list(uniq)
    return {
        "offer_count": len(uniq),
        "related_ok": related_ok,
        "related_fail": related_fail,
        "sync": sync,
    }
