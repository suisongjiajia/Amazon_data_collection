from typing import Any

from repositories import draft_repository


def create_listing_draft(
    product_master_id: int,
    *,
    shop_name: str,
    marketplace: str | None = None,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
) -> dict[str, Any]:
    return draft_repository.create_listing_draft(
        product_master_id,
        shop_name=shop_name,
        marketplace=marketplace,
        title=title,
        price=price,
        quantity=quantity,
    )


def list_listing_drafts(limit: int = 100) -> list[dict[str, Any]]:
    return draft_repository.list_listing_drafts(limit)


def update_listing_draft(
    draft_id: int,
    *,
    title: str | None = None,
    bullet_points: list[str] | None = None,
    description: str | None = None,
    search_terms: str | None = None,
    attributes: dict[str, Any] | None = None,
    status: str | None = None,
    change_note: str | None = None,
) -> dict[str, Any]:
    return draft_repository.update_listing_draft(
        draft_id,
        title=title,
        bullet_points=bullet_points,
        description=description,
        search_terms=search_terms,
        attributes=attributes,
        status=status,
        change_note=change_note,
    )


def update_listing_draft_variant(
    draft_variant_id: int,
    *,
    price: float | None = None,
    quantity: int | None = None,
    fulfillment_channel: str | None = None,
    external_product_id: str | None = None,
    external_product_id_type: str | None = None,
) -> dict[str, Any]:
    return draft_repository.update_listing_draft_variant(
        draft_variant_id,
        price=price,
        quantity=quantity,
        fulfillment_channel=fulfillment_channel,
        external_product_id=external_product_id,
        external_product_id_type=external_product_id_type,
    )
