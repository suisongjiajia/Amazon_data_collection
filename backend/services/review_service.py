from __future__ import annotations

from typing import Any

from db.ozon_workflow import create_review_record, get_product_edit, list_review_records
from services.ozon_listing_payload import preview_listing


def approve(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    record = create_review_record(edit_id, result="approved", note=note, reviewer=reviewer)
    return {"review": record, "edit": get_product_edit(edit_id)}


def reject(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    record = create_review_record(edit_id, result="rejected", note=note, reviewer=reviewer)
    return {"review": record, "edit": get_product_edit(edit_id)}


def list_records(edit_id: int | None = None, limit: int = 50) -> list[dict]:
    return list_review_records(edit_id, limit)


def get_listing_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    return {
        "edit": edit,
        "preview": preview,
        "saved_listing": edit.get("listing_payload"),
    }
