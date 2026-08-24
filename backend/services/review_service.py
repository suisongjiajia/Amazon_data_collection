from __future__ import annotations

from db.ozon_workflow import create_review_record, list_review_records


def approve(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    return create_review_record(edit_id, result="approved", note=note, reviewer=reviewer)


def reject(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    return create_review_record(edit_id, result="rejected", note=note, reviewer=reviewer)


def list_records(edit_id: int | None = None, limit: int = 50) -> list[dict]:
    return list_review_records(edit_id, limit)
