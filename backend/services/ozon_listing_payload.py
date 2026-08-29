from __future__ import annotations

import os
import re
from typing import Any

from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError


def _parse_dimension_mm(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    try:
        return int(float(match.group(1).replace(",", ".")))
    except ValueError:
        return None


def _parse_dimensions_from_attributes(attributes: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    depth = None
    width = None
    height = None
    for key, value in attributes.items():
        lower = str(key).lower()
        if any(alias in lower for alias in ("длина", "length", "长度", "depth")):
            depth = _parse_dimension_mm(value) or depth
        if any(alias in lower for alias in ("ширина", "width", "宽度")):
            width = _parse_dimension_mm(value) or width
        if any(alias in lower for alias in ("высота", "height", "高度")):
            height = _parse_dimension_mm(value) or height

    size_text = attributes.get("size") or attributes.get("尺寸")
    if isinstance(size_text, str) and "×" in size_text:
        parts = [part.strip() for part in size_text.split("×")]
        nums = [_parse_dimension_mm(part) for part in parts]
        nums = [num for num in nums if num is not None]
        if len(nums) >= 3:
            return nums[0], nums[1], nums[2]
        if len(nums) == 2:
            return nums[0], nums[1], None
    return depth, width, height


def _parse_weight_grams(attributes: dict[str, Any], size_weight: str | None = None) -> int | None:
    for key, value in attributes.items():
        lower = str(key).lower()
        if any(alias in lower for alias in ("вес", "weight", "重量", "масса")):
            text = str(value).lower()
            num = _parse_dimension_mm(value)
            if num is None:
                continue
            if "kg" in text or "кг" in text or "千克" in text:
                return int(num * 1000)
            return num
    if size_weight:
        num = _parse_dimension_mm(size_weight)
        if num is not None:
            return num
    return None


def _as_int_id(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _build_no_brand_attribute() -> dict[str, Any]:
    attribute_id = _as_int_id(os.getenv("OZON_BRAND_ATTRIBUTE_ID", "85")) or 85
    dictionary_value_id = _as_int_id(os.getenv("OZON_NO_BRAND_DICTIONARY_VALUE_ID", "126745801"))
    if dictionary_value_id:
        return {
            "id": attribute_id,
            "values": [{"dictionary_value_id": dictionary_value_id}],
        }
    return {
        "id": attribute_id,
        "values": [{"value": "Нет бренда"}],
    }


def _composed_description(edit: dict[str, Any]) -> str:
    description_parts = [edit.get("description") or ""]
    bullet_points = edit.get("bullet_points") or []
    if bullet_points:
        description_parts.append("\n".join(f"• {point}" for point in bullet_points))
    return "\n\n".join(part.strip() for part in description_parts if part and str(part).strip())


def collect_listing_issues(edit: dict[str, Any]) -> list[dict[str, Any]]:
    """软校验上架 Listing，返回 issues（error / warning）。"""
    issues: list[dict[str, Any]] = []
    attributes = edit.get("attributes") or {}
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]

    if not str(edit.get("title") or "").strip():
        issues.append({"code": "MISSING_TITLE", "severity": "error", "message": "缺少标题"})
    if not _composed_description(edit):
        issues.append({"code": "MISSING_DESCRIPTION", "severity": "warning", "message": "描述为空，建议补充"})
    if not images:
        issues.append({"code": "MISSING_IMAGES", "severity": "error", "message": "至少需要 1 张图片"})

    description_category_id = _as_int_id(
        attributes.get("description_category_id") or attributes.get("category_id")
    )
    type_id = _as_int_id(attributes.get("type_id"))
    if description_category_id is None:
        issues.append(
            {
                "code": "MISSING_CATEGORY_ID",
                "severity": "error",
                "message": "缺少 description_category_id，请重新采集或在编辑页手动填写",
            }
        )
    if type_id is None:
        issues.append(
            {
                "code": "MISSING_TYPE_ID",
                "severity": "error",
                "message": "缺少 type_id，请重新采集或在编辑页手动填写",
            }
        )

    variants = edit.get("variants") or []
    usable = 0
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        usable += 1
        if variant.get("price") is None:
            issues.append(
                {
                    "code": "MISSING_PRICE",
                    "severity": "error",
                    "message": f"变体 {sku} 缺少价格",
                }
            )
    if usable == 0:
        issues.append({"code": "MISSING_SKU", "severity": "error", "message": "没有可发布的 SKU 变体"})

    if not _as_int_id(os.getenv("OZON_WAREHOUSE_ID")):
        issues.append(
            {
                "code": "MISSING_WAREHOUSE",
                "severity": "warning",
                "message": "未配置 OZON_WAREHOUSE_ID，真实发布时不会推送 rFBS 库存",
            }
        )

    depth, width, height = _parse_dimensions_from_attributes(attributes)
    weight = _parse_weight_grams(attributes)
    if depth is None or width is None or height is None:
        issues.append(
            {
                "code": "MISSING_DIMENSIONS",
                "severity": "warning",
                "message": "尺寸不完整，Ozon 可能拒收或部分字段缺失",
            }
        )
    if weight is None:
        issues.append(
            {
                "code": "MISSING_WEIGHT",
                "severity": "warning",
                "message": "缺少重量，建议补充后发布",
            }
        )
    return issues


def build_listing_summary(edit: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    attributes = edit.get("attributes") or {}
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
    return {
        "title": edit.get("title"),
        "description": edit.get("description"),
        "bullet_points": edit.get("bullet_points") or [],
        "images": images,
        "description_category_id": attributes.get("description_category_id") or attributes.get("category_id"),
        "type_id": attributes.get("type_id"),
        "fulfillment": attributes.get("fulfillment") or "rFBS",
        "brand_mode": attributes.get("brand_mode") or "no_brand",
        "attributes": attributes,
        "variants": [
            {
                "sku": variant.get("sku"),
                "title": variant.get("title") or edit.get("title"),
                "price": variant.get("price"),
                "quantity": variant.get("quantity"),
                "image_url": variant.get("image_url"),
            }
            for variant in (edit.get("variants") or [])
            if str(variant.get("sku") or "").strip()
        ],
        "payload_offer_ids": [item.get("offer_id") for item in (items or [])],
        "payload_item_count": len(items or []),
    }


def preview_listing(edit: dict[str, Any]) -> dict[str, Any]:
    issues = collect_listing_issues(edit)
    errors = [item for item in issues if item.get("severity") == "error"]
    items: list[dict[str, Any]] | None = None
    stocks: list[dict[str, Any]] | None = None
    build_error: str | None = None

    if not errors:
        try:
            items = build_import_items(edit)
            warehouse_id = _as_int_id(os.getenv("OZON_WAREHOUSE_ID"))
            if warehouse_id:
                stocks = build_stock_items(edit, warehouse_id)
        except OzonSellerError as exc:
            build_error = str(exc)
            issues.append({"code": "BUILD_FAILED", "severity": "error", "message": build_error})
            errors.append(issues[-1])

    return {
        "ok": not errors and items is not None,
        "issues": issues,
        "summary": build_listing_summary(edit, items),
        "payload_items": items or [],
        "stock_items": stocks or [],
        "build_error": build_error,
    }


def build_import_items(edit: dict[str, Any]) -> list[dict[str, Any]]:
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
    attributes = edit.get("attributes") or {}
    depth, width, height = _parse_dimensions_from_attributes(attributes)
    weight = _parse_weight_grams(attributes)

    description_category_id = _as_int_id(
        attributes.get("description_category_id") or attributes.get("category_id")
    )
    type_id = _as_int_id(attributes.get("type_id"))
    if description_category_id is None or type_id is None:
        raise OzonSellerError(
            "缺少 description_category_id 或 type_id，请重新采集或在编辑页手动填写后再发布"
        )

    description = _composed_description(edit)

    vat = str(os.getenv("OZON_VAT", "0") or "0").strip() or "0"
    currency_code = (os.getenv("OZON_CURRENCY_CODE") or "RUB").strip() or "RUB"
    brand_attribute = _build_no_brand_attribute()

    items: list[dict[str, Any]] = []
    for variant in edit.get("variants") or []:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        price = variant.get("price")
        if price is None:
            raise OzonSellerError(f"变体 {sku} 缺少价格，请先填写价格后再发布")
        item_images = images[:15] or ([variant.get("image_url")] if variant.get("image_url") else [])
        item: dict[str, Any] = {
            "offer_id": sku,
            "name": str(variant.get("title") or edit.get("title") or sku),
            "description": description,
            "description_category_id": description_category_id,
            "type_id": type_id,
            "price": str(int(price) if float(price).is_integer() else price),
            "vat": vat,
            "currency_code": currency_code,
            "attributes": [brand_attribute],
            "images": item_images,
        }
        if item_images:
            item["primary_image"] = item_images[0]
        if depth is not None:
            item["depth"] = depth
        if width is not None:
            item["width"] = width
        if height is not None:
            item["height"] = height
        if any(key in item for key in ("depth", "width", "height")):
            item["dimension_unit"] = "mm"
        if weight is not None:
            item["weight"] = weight
            item["weight_unit"] = "g"
        items.append(item)

    if not items:
        raise OzonSellerError("没有可发布的 SKU 变体")
    return items


def build_stock_items(edit: dict[str, Any], warehouse_id: int) -> list[dict[str, Any]]:
    stocks: list[dict[str, Any]] = []
    for variant in edit.get("variants") or []:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        try:
            quantity = int(variant.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        stocks.append(
            {
                "offer_id": sku,
                "stock": max(0, quantity),
                "warehouse_id": warehouse_id,
            }
        )
    return stocks


def publish_edit_to_ozon(edit: dict[str, Any]) -> dict[str, Any]:
    items = build_import_items(edit)
    client = OzonSellerClient()
    import_result = client.import_products(items)

    stock_result = None
    warehouse_id = _as_int_id(os.getenv("OZON_WAREHOUSE_ID"))
    if warehouse_id:
        stocks = build_stock_items(edit, warehouse_id)
        if stocks:
            stock_result = client.update_stocks(stocks)

    return {
        "import": import_result,
        "stocks": stock_result,
        "fulfillment": "rFBS",
    }
