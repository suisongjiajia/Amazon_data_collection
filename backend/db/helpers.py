from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse
from uuid import uuid4


def build_code(prefix: str) -> str:
    return f"{prefix}-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}"


def extract_marketplace(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.hostname


def build_variant_key(
    variant_attributes: dict[str, Any] | None = None,
    variant_dimensions: Iterable[str] | None = None,
    *,
    color: str | None = None,
    size: str | None = None,
) -> str | None:
    attributes = {str(key): str(value) for key, value in (variant_attributes or {}).items() if value}
    ordered_parts: list[str] = []
    seen_values: set[str] = set()

    for dimension in variant_dimensions or []:
        value = _find_variant_attribute_value(attributes, str(dimension))
        if value and value not in seen_values:
            ordered_parts.append(f"{dimension}: {value}")
            seen_values.add(value)

    if not ordered_parts:
        for key, value in attributes.items():
            if value not in seen_values:
                ordered_parts.append(f"{key}: {value}")
                seen_values.add(value)

    if not ordered_parts:
        for part in (color, size):
            if part and part not in seen_values:
                ordered_parts.append(part)
                seen_values.add(part)

    return " / ".join(ordered_parts) if ordered_parts else None


def build_publish_payload(
    draft: dict[str, Any],
    draft_variant: dict[str, Any],
    shop_name: str,
    marketplace: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    title = draft.get("title")
    seller_sku = draft_variant.get("seller_sku")
    price = draft_variant.get("price")

    if not title:
        issues.append({"field": "title", "message": "Title is required before publishing"})
    if not seller_sku:
        issues.append({"field": "seller_sku", "message": "Seller SKU is required before publishing"})
    if price in (None, 0):
        issues.append({"field": "price", "message": "Price must be set before publishing"})

    payload = {
        "shop_name": shop_name,
        "marketplace": marketplace,
        "draft_id": draft["id"],
        "variant_id": draft_variant["variant_id"],
        "seller_sku": seller_sku,
        "title": title,
        "bullet_points": draft.get("bullet_points") or [],
        "description": draft.get("description"),
        "search_terms": draft.get("search_terms"),
        "attributes": draft.get("attributes") or {},
        "price": price,
        "quantity": draft_variant.get("quantity", 0),
        "fulfillment_channel": draft_variant.get("fulfillment_channel"),
        "external_product_id": draft_variant.get("external_product_id"),
        "external_product_id_type": draft_variant.get("external_product_id_type"),
    }
    return payload, issues


def build_live_listing_record(
    publish_task_item_id: int,
    draft: dict[str, Any],
    draft_variant: dict[str, Any],
    shop_name: str,
    marketplace: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    draft_attributes = draft.get("attributes") or {}
    reference_asin = draft_attributes.get("reference_asin")
    reference_parent_asin = draft_attributes.get("reference_parent_asin")
    if isinstance(reference_asin, str):
        reference_asin = reference_asin.strip() or None
    else:
        reference_asin = None
    if isinstance(reference_parent_asin, str):
        reference_parent_asin = reference_parent_asin.strip() or None
    else:
        reference_parent_asin = None

    return {
        "publish_task_item_id": publish_task_item_id,
        "draft_id": draft["id"],
        "variant_id": draft_variant["variant_id"],
        "shop_name": shop_name,
        "marketplace": marketplace,
        "seller_sku": draft_variant["seller_sku"],
        "asin": reference_asin,
        "parent_asin": reference_parent_asin,
        "listing_status": "published",
        "price": draft_variant.get("price"),
        "quantity": draft_variant.get("quantity", 0),
        "live_payload": payload,
        "last_sync_at": datetime.now(),
    }


def _find_variant_attribute_value(attributes: dict[str, str], dimension: str) -> str | None:
    normalized_dimension = _normalize_dimension_key(dimension)
    for key, value in attributes.items():
        if _normalize_dimension_key(key) == normalized_dimension:
            return value
    return None


def _normalize_dimension_key(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").split())
