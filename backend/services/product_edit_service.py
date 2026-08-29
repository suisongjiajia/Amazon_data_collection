from __future__ import annotations

from typing import Any

from db.ozon_workflow import (
    create_product_edit,
    delete_product_edit,
    get_product_edit,
    list_product_edits,
    reopen_product_edit,
    submit_product_edit_for_review,
    update_product_edit,
    update_product_edit_variant,
)
from services.ozon_listing_payload import preview_listing


def create_edit(raw_product_family_id: int) -> dict[str, Any]:
    return create_product_edit(raw_product_family_id)


def get_edit(edit_id: int) -> dict[str, Any]:
    return get_product_edit(edit_id)


def list_edits(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return list_product_edits(status, limit)


def update_edit(
    edit_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    bullet_points: list[str] | None = None,
    images: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return update_product_edit(
        edit_id,
        title=title,
        description=description,
        bullet_points=bullet_points,
        images=images,
        attributes=attributes,
    )


def update_variant(
    variant_id: int,
    *,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
    image_url: str | None = None,
    variant_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return update_product_edit_variant(
        variant_id,
        title=title,
        price=price,
        quantity=quantity,
        image_url=image_url,
        variant_attributes=variant_attributes,
    )


def preview_edit_listing(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    return {
        **preview,
        "edit_id": edit_id,
        "edit_status": edit.get("status"),
        "listing_built_at": edit.get("listing_built_at"),
        "saved_listing": edit.get("listing_payload"),
    }


def build_listing(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in ("draft", "editing", "rejected", "listing_ready"):
        raise ValueError("当前状态不可生成 Listing，请先重新打开编辑")
    preview = preview_listing(edit)
    if not preview["ok"]:
        return {
            **preview,
            "edit_id": edit_id,
            "edit": edit,
            "saved": False,
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
        status="listing_ready",
        set_listing_built=True,
    )
    return {
        **preview,
        "edit_id": edit_id,
        "edit": updated,
        "saved": True,
    }


def submit_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    if not preview["ok"]:
        messages = "; ".join(
            item["message"] for item in preview["issues"] if item.get("severity") == "error"
        )
        raise ValueError(f"Listing 校验未通过：{messages or '存在错误'}")
    if edit["status"] != "listing_ready" or not edit.get("listing_payload"):
        raise ValueError("请先生成 Listing（校验通过并保存快照）后再提交审核")
    return submit_product_edit_for_review(edit_id)


def reopen_edit(edit_id: int) -> dict[str, Any]:
    return reopen_product_edit(edit_id)


def delete_edit(edit_id: int) -> dict[str, Any]:
    return delete_product_edit(edit_id)
