from __future__ import annotations

from typing import Any

from db.connection import get_connection
from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import (
    create_review_record,
    get_product_edit,
    list_review_records,
    list_supplier_candidates,
    update_product_edit,
)
from db.shop_pipeline import find_pipeline_item_by_edit
from services.ozon_listing_payload import preview_listing
from services.sourcing_service import _enrich_ozon_family_for_display


def approve(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    record = create_review_record(edit_id, result="approved", note=note, reviewer=reviewer)
    return {"review": record, "edit": get_product_edit(edit_id)}


def reject(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    record = create_review_record(edit_id, result="rejected", note=note, reviewer=reviewer)
    return {"review": record, "edit": get_product_edit(edit_id)}


def list_records(edit_id: int | None = None, limit: int = 50) -> list[dict]:
    return list_review_records(edit_id, limit)


def update_prices(
    edit_id: int,
    *,
    apply_all_price: float | None = None,
    variant_prices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """审核中改价：更新变体售价并重建 Listing 快照，保持/升为 pending_review。"""
    edit = get_product_edit(edit_id)
    status = str(edit.get("status") or "")
    if status not in {"pending_review", "needs_fix"}:
        raise ValueError("仅待审核或待修复的商品可在审核中心改价")

    variants = list(edit.get("variants") or [])
    if not variants:
        raise ValueError("没有可改价的变体")

    price_map: dict[int, float] = {}
    if apply_all_price is not None:
        if float(apply_all_price) <= 0:
            raise ValueError("售价必须大于 0")
        for variant in variants:
            price_map[int(variant["id"])] = float(apply_all_price)
    for item in variant_prices or []:
        vid = int(item["variant_id"])
        price = float(item["price"])
        if price <= 0:
            raise ValueError(f"变体 {vid} 售价必须大于 0")
        price_map[vid] = price

    if not price_map:
        raise ValueError("请提供 apply_all_price 或 variant_prices")

    allowed_ids = {int(v["id"]) for v in variants}
    unknown = [vid for vid in price_map if vid not in allowed_ids]
    if unknown:
        raise ValueError(f"变体不属于该编辑草稿：{unknown}")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for variant_id, price in price_map.items():
                cursor.execute(
                    "UPDATE product_edit_variant SET price = %s WHERE id = %s AND edit_id = %s",
                    (price, variant_id, edit_id),
                )

    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    if not preview["ok"]:
        messages = "; ".join(
            issue.get("message") or ""
            for issue in (preview.get("issues") or [])
            if issue.get("severity") == "error"
        )
        return {
            "ok": False,
            "saved_prices": True,
            "listing_rebuilt": False,
            "message": messages or "价格已保存，但 Listing 校验未通过",
            "edit": edit,
            "preview": preview,
            "bundle": get_listing_for_review(edit_id),
        }

    snapshot = {
        "summary": preview["summary"],
        "payload_items": preview["payload_items"],
        "stock_items": preview["stock_items"],
        "issues": preview["issues"],
    }
    updated = update_product_edit(
        edit_id,
        listing_payload=snapshot,
        status="pending_review",
        set_listing_built=True,
    )
    return {
        "ok": True,
        "saved_prices": True,
        "listing_rebuilt": True,
        "message": "价格已更新并写入 Listing",
        "edit": updated,
        "preview": preview,
        "bundle": get_listing_for_review(edit_id),
    }


def get_listing_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    family_id = int(edit["raw_product_family_id"])
    family = get_ozon_product_family(family_id)
    product = _enrich_ozon_family_for_display(family)

    candidates = list_supplier_candidates(family_id, limit=20)
    selected = [item for item in candidates if item.get("status") == "selected"]
    others = [item for item in candidates if item.get("status") != "selected"]
    others_sorted = sorted(others, key=lambda c: float(c.get("match_score") or 0), reverse=True)
    suppliers = selected + others_sorted
    suppliers = suppliers[:5] if not selected else selected + others_sorted[: max(0, 5 - len(selected))]

    pipeline_item = find_pipeline_item_by_edit(edit_id)
    stage = (pipeline_item or {}).get("stage_detail") or {}
    pricing = stage.get("pricing")
    attrs = edit.get("attributes") or {}
    price_summary = {
        "list_price": (edit.get("variants") or [{}])[0].get("price"),
        "currency_code": attrs.get("currency_code"),
        "formula": attrs.get("pricing_formula"),
        "freight_cny": attrs.get("freight_cny"),
        "freight_channel": attrs.get("freight_channel"),
        "pricing_error": attrs.get("pricing_error") or attrs.get("pipeline_error"),
    }
    if pricing is None and attrs.get("pricing_formula"):
        pricing = {
            "pricing": {
                "list_price": price_summary["list_price"],
                "formula": attrs.get("pricing_formula"),
                "currency_code": attrs.get("currency_code"),
            },
            "freight": {
                "freight_cny": attrs.get("freight_cny"),
                "channel_name": attrs.get("freight_channel"),
            },
        }

    saved = edit.get("listing_payload")
    if isinstance(saved, dict) and saved.get("summary") is not None:
        preview = {
            "ok": True,
            "issues": saved.get("issues") or [],
            "summary": saved.get("summary") or {},
            "payload_items": saved.get("payload_items") or [],
            "stock_items": saved.get("stock_items") or [],
            "build_error": None,
            "from_snapshot": True,
        }
    else:
        preview = preview_listing(edit)
        preview["from_snapshot"] = False

    return {
        "edit": edit,
        "preview": preview,
        "saved_listing": saved,
        "product": product,
        "suppliers": suppliers,
        "selected_supplier": selected[0] if selected else (suppliers[0] if suppliers else None),
        "pricing": pricing,
        "price_summary": price_summary,
        "pipeline_item": pipeline_item,
        "pipeline_error": attrs.get("pipeline_error"),
        "failure_kind": attrs.get("failure_kind") or (pipeline_item or {}).get("status"),
    }
