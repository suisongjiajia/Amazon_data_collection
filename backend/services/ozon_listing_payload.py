from __future__ import annotations

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


def build_import_items(edit: dict[str, Any]) -> list[dict[str, Any]]:
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
    attributes = edit.get("attributes") or {}
    depth, width, height = _parse_dimensions_from_attributes(attributes)
    weight = _parse_weight_grams(attributes)

    description_parts = [edit.get("description") or ""]
    bullet_points = edit.get("bullet_points") or []
    if bullet_points:
        description_parts.append("\n".join(f"• {point}" for point in bullet_points))
    description = "\n\n".join(part.strip() for part in description_parts if part and str(part).strip())

    items: list[dict[str, Any]] = []
    for variant in edit.get("variants") or []:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        price = variant.get("price")
        if price is None:
            raise OzonSellerError(f"变体 {sku} 缺少价格，请先保存 AI 生成的价格")
        item: dict[str, Any] = {
            "offer_id": sku,
            "name": str(variant.get("title") or edit.get("title") or sku),
            "description": description,
            "price": str(int(price) if float(price).is_integer() else price),
            "vat": "0",
            "currency_code": "RUB",
            "images": images[:15] or ([variant.get("image_url")] if variant.get("image_url") else []),
        }
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


def publish_edit_to_ozon(edit: dict[str, Any]) -> dict[str, Any]:
    items = build_import_items(edit)
    client = OzonSellerClient()
    return client.import_products(items)
