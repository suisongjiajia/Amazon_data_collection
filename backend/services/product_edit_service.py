from __future__ import annotations

from typing import Any

from db.ozon_workflow import (
    create_product_edit,
    delete_product_edit,
    get_product_edit,
    list_product_edits,
    submit_product_edit_for_review,
    update_product_edit,
    update_product_edit_variant,
)


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


def submit_for_review(edit_id: int) -> dict[str, Any]:
    return submit_product_edit_for_review(edit_id)


def delete_edit(edit_id: int) -> dict[str, Any]:
    return delete_product_edit(edit_id)
