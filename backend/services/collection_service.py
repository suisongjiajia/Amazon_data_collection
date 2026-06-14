from __future__ import annotations

from typing import Any

import database
from collector import AmazonCollector
from collector.models import ProductInfo


def collect_products(source_url: str) -> list[dict[str, Any]]:
    products = AmazonCollector().collect(source_url)
    families = build_product_families(products)
    return database.save_raw_product_families(None, families)


def run_collection_task(source_url: str) -> dict[str, Any]:
    task = database.create_collection_task(source_url)

    try:
        products = AmazonCollector().collect(source_url)
        families = build_product_families(products)
        saved_families = database.save_raw_product_families(int(task["id"]), families)
        task = database.finish_collection_task(
            int(task["id"]),
            status="completed",
            total_count=sum(len(family.get("variants") or []) for family in families),
            success_count=sum(len(family.get("variants") or []) for family in families),
            fail_count=0,
        )
        return {
            "task": task,
            "families": saved_families,
        }
    except Exception as exc:
        database.finish_collection_task(
            int(task["id"]),
            status="failed",
            total_count=0,
            success_count=0,
            fail_count=1,
            error_message=str(exc),
        )
        raise


def build_product_families(products: list[ProductInfo]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    variant_orders: dict[str, list[str]] = {}

    for product in products:
        family_key = _build_family_key(product)
        if family_key not in grouped:
            grouped[family_key] = {
                "family_key": family_key,
                "parent_asin": None,
                "marketplace": database._extract_marketplace(product.source_url),
                "source_url": product.source_url,
                "title": product.title,
                "brand": product.brand,
                "rating": product.rating,
                "review_count": product.review_count,
                "main_image_url": product.main_image_url,
                "variant_dimensions": [],
                "bullet_points": product.bullet_points or [],
                "raw_payload": {
                    "source_asins": [],
                },
                "variants": [],
            }
            variant_orders[family_key] = []

        family = grouped[family_key]
        dimensions = variant_orders[family_key]
        for key in (product.variant_attributes or {}).keys():
            normalized_key = str(key).strip()
            if normalized_key and normalized_key not in dimensions:
                dimensions.append(normalized_key)

        family["title"] = family["title"] or product.title
        family["brand"] = family["brand"] or product.brand
        family["rating"] = family["rating"] or product.rating
        family["review_count"] = family["review_count"] or product.review_count
        family["main_image_url"] = family["main_image_url"] or product.main_image_url
        family["source_url"] = family["source_url"] or product.source_url

        raw_payload = family["raw_payload"]
        source_asins = raw_payload.setdefault("source_asins", [])
        if product.asin and product.asin not in source_asins:
            source_asins.append(product.asin)

        family["variants"].append(
            {
                "asin": product.asin,
                "parent_asin": None,
                "source_url": product.source_url,
                "title": product.title,
                "price_text": product.price,
                "main_image_url": product.main_image_url,
                "size": product.size,
                "color": product.color,
                "variant_attributes": product.variant_attributes or {},
                "raw_payload": product.to_dict(),
                "snapshot_time": product.collected_at,
            }
        )

    results: list[dict[str, Any]] = []
    for family_key, family in grouped.items():
        family["variant_dimensions"] = variant_orders[family_key]
        family["variants"].sort(key=_variant_sort_key)
        if family["variants"]:
            family["source_url"] = family["source_url"] or family["variants"][0].get("source_url")
            family["main_image_url"] = family["main_image_url"] or family["variants"][0].get("main_image_url")
        results.append(family)

    return results


def _build_family_key(product: ProductInfo) -> str:
    explicit_key = (product.family_key or "").strip()
    if explicit_key:
        return explicit_key

    sibling_asins = sorted({asin.strip().upper() for asin in product.family_variant_asins if asin})
    if sibling_asins:
        return "|".join(sibling_asins)

    return (product.asin or product.source_url or "unknown").strip()


def _variant_sort_key(variant: dict[str, Any]) -> tuple[str, str, str]:
    attributes = variant.get("variant_attributes") or {}
    first_value = next(iter(attributes.values()), "")
    return (
        str(first_value or ""),
        str(variant.get("color") or ""),
        str(variant.get("size") or ""),
    )
