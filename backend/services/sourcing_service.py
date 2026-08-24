from __future__ import annotations

from typing import Any

from collector.alibaba1688 import Alibaba1688Client
from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import (
    create_sourcing_task,
    finish_sourcing_task,
    list_sourcing_tasks,
    list_supplier_candidates,
    save_supplier_candidates,
    update_supplier_candidate_status,
)


def _format_rub_price(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, (int, float)):
        amount = int(value) if float(value).is_integer() else float(value)
        return f"{amount} ₽"
    return str(value)


def _derive_size_and_weight(
    attributes: dict[str, Any],
    details: dict[str, Any],
    variant: dict[str, Any],
    variant_attrs: dict[str, Any],
) -> tuple[str | None, str | None]:
    size = (
        variant.get("size")
        or details.get("size")
        or variant_attrs.get("size")
        or variant_attrs.get("尺寸")
    )
    weight = (
        details.get("weight")
        or variant_attrs.get("weight")
        or variant_attrs.get("重量")
    )
    if size or weight:
        return size, weight

    length = _find_display_attribute(attributes, ("длина", "length", "长度"))
    width = _find_display_attribute(attributes, ("ширина", "width", "宽度"))
    height = _find_display_attribute(attributes, ("высота", "height", "高度"))
    dims = [value for value in (length, width, height) if value]
    derived_size = f"{'×'.join(dims)} mm" if dims else None
    derived_weight = _find_display_attribute(attributes, ("вес", "weight", "重量", "масса"))
    return derived_size, derived_weight


def _find_display_attribute(attributes: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    for key, value in attributes.items():
        lower = str(key).lower()
        if any(alias in lower for alias in aliases):
            text = str(value).strip()
            if text:
                return text
    return None


def _enrich_ozon_family_for_display(family: dict[str, Any]) -> dict[str, Any]:
    raw = family.get("raw_payload") or {}
    inner = raw.get("rawPayload") or {}
    details = inner.get("details") or raw.get("details") or {}
    variant = (family.get("variants") or [None])[0] or {}
    variant_attrs = variant.get("variant_attributes") or {}
    attributes = dict(details.get("attributes") or variant_attrs or {})

    images = details.get("images") or []
    if not images and family.get("main_image_url"):
        images = [family.get("main_image_url")]

    size, weight = _derive_size_and_weight(attributes, details, variant, variant_attrs)
    category_name = family.get("category_name") or details.get("category_name")

    return {
        "id": family.get("id"),
        "external_id": family.get("external_id"),
        "title": family.get("title"),
        "brand": family.get("brand"),
        "source_url": family.get("source_url"),
        "main_image_url": family.get("main_image_url"),
        "rating": family.get("rating"),
        "review_count": family.get("review_count"),
        "category_name": category_name,
        "sales_rank": family.get("sales_rank"),
        "hot_score": family.get("hot_score"),
        "price_text": _format_rub_price(variant.get("price_text") or details.get("price") or raw.get("price")),
        "description": (details.get("description") or "").strip(),
        "images": images,
        "size": size,
        "weight": weight,
        "attributes": attributes,
        "sku": details.get("sku") or family.get("external_id"),
        "variant_count": family.get("variant_count") or len(family.get("variants") or []),
        "variants": family.get("variants") or [],
    }


def get_sourcing_detail(raw_product_family_id: int) -> dict[str, Any]:
    family = get_ozon_product_family(raw_product_family_id)
    candidates = list_supplier_candidates(raw_product_family_id, limit=100)
    return {
        "product": _enrich_ozon_family_for_display(family),
        "candidates": candidates,
    }


def search_suppliers_by_image(raw_product_family_id: int) -> dict[str, Any]:
    family = get_ozon_product_family(raw_product_family_id)
    image_url = family.get("main_image_url")
    if not image_url:
        raise ValueError("商品缺少主图，无法搜货源")

    task = create_sourcing_task(raw_product_family_id, image_url)

    try:
        candidates = Alibaba1688Client().search_suppliers_by_image_url(image_url)
        saved = save_supplier_candidates(
            raw_product_family_id,
            candidates,
            sourcing_task_id=int(task["id"]),
        )
        task = finish_sourcing_task(
            int(task["id"]),
            status="completed",
            candidate_count=len(saved),
        )
        return {"task": task, "candidates": saved}
    except Exception as exc:
        finish_sourcing_task(
            int(task["id"]),
            status="failed",
            candidate_count=0,
            error_message=str(exc),
        )
        raise


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return list_sourcing_tasks(limit)


def list_candidates(raw_product_family_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return list_supplier_candidates(raw_product_family_id, limit)


def select_candidate(candidate_id: int) -> dict[str, Any]:
    return update_supplier_candidate_status(candidate_id, "selected")


def unselect_candidate(candidate_id: int) -> dict[str, Any]:
    return update_supplier_candidate_status(candidate_id, "candidate")
