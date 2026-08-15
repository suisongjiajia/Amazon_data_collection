from __future__ import annotations

from typing import Any

from db.connection import check_db, get_connection
from db.helpers import (
    build_code as _build_code,
    build_live_listing_record as _build_live_listing_record,
    build_publish_payload as _build_publish_payload,
    build_variant_key as _build_variant_key,
    extract_marketplace as _extract_marketplace,
)
from db.raw_catalog import (
    attach_raw_variants,
    create_collection_task,
    finish_collection_task,
    get_collection_task,
    get_raw_product_families,
    get_raw_product_families_for_task,
    get_raw_product_family,
    list_collection_tasks,
    list_listing_live,
    list_raw_product_families,
    save_raw_product_families,
)
from db.schema import CREATE_TABLE_STATEMENTS, DROP_TABLES, JSON_FIELDS, init_db, reset_db
from db.serialization import (
    fetch_all as _fetch_all,
    fetch_one as _fetch_one,
    from_json as _from_json,
    normalize_row as _normalize_row,
    to_json as _to_json,
)


def create_selection(
    raw_product_family_id: int,
    *,
    owner: str | None = None,
    remark: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    from repositories.selection_repository import create_selection as repo_create_selection

    return repo_create_selection(
        raw_product_family_id,
        owner=owner,
        remark=remark,
        score=score,
    )


def update_selection_variant_scope(
    selection_id: int,
    raw_product_variant_ids: list[int],
) -> dict[str, Any]:
    from repositories.selection_repository import (
        update_selection_variant_scope as repo_update_selection_variant_scope,
    )

    return repo_update_selection_variant_scope(selection_id, raw_product_variant_ids)


def list_selections(limit: int = 100) -> list[dict[str, Any]]:
    from repositories.selection_repository import list_selections as repo_list_selections

    return repo_list_selections(limit)


def get_selection(selection_id: int) -> dict[str, Any]:
    from repositories.selection_repository import get_selection as repo_get_selection

    return repo_get_selection(selection_id)


def create_product_from_selection(
    selection_id: int,
    *,
    spu_code: str | None = None,
    product_name: str | None = None,
    brand: str | None = None,
    target_marketplace: str | None = None,
    default_cost: float | None = None,
    stock_qty: int = 0,
) -> dict[str, Any]:
    from repositories.product_repository import create_product_from_selection as repo_create_product

    return repo_create_product(
        selection_id,
        spu_code=spu_code,
        product_name=product_name,
        brand=brand,
        target_marketplace=target_marketplace,
        default_cost=default_cost,
        stock_qty=stock_qty,
    )


def list_products(limit: int = 100) -> list[dict[str, Any]]:
    from repositories.product_repository import list_products as repo_list_products

    return repo_list_products(limit)


def get_product(product_id: int) -> dict[str, Any]:
    from repositories.product_repository import get_product as repo_get_product

    return repo_get_product(product_id)


def create_listing_draft(
    product_master_id: int,
    *,
    shop_name: str,
    marketplace: str | None = None,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
) -> dict[str, Any]:
    from repositories.draft_repository import create_listing_draft as repo_create_listing_draft

    return repo_create_listing_draft(
        product_master_id,
        shop_name=shop_name,
        marketplace=marketplace,
        title=title,
        price=price,
        quantity=quantity,
    )


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
    from repositories.draft_repository import update_listing_draft as repo_update_listing_draft

    return repo_update_listing_draft(
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
    from repositories.draft_repository import (
        update_listing_draft_variant as repo_update_listing_draft_variant,
    )

    return repo_update_listing_draft_variant(
        draft_variant_id,
        price=price,
        quantity=quantity,
        fulfillment_channel=fulfillment_channel,
        external_product_id=external_product_id,
        external_product_id_type=external_product_id_type,
    )


def list_listing_drafts(limit: int = 100) -> list[dict[str, Any]]:
    from repositories.draft_repository import list_listing_drafts as repo_list_listing_drafts

    return repo_list_listing_drafts(limit)


def get_listing_draft(draft_id: int) -> dict[str, Any]:
    from repositories.draft_repository import get_listing_draft as repo_get_listing_draft

    return repo_get_listing_draft(draft_id)


def create_publish_task(
    draft_ids: list[int],
    *,
    shop_name: str | None = None,
    marketplace: str | None = None,
    simulate: bool = True,
) -> dict[str, Any]:
    from repositories.publish_repository import create_publish_task as repo_create_publish_task

    return repo_create_publish_task(
        draft_ids,
        shop_name=shop_name,
        marketplace=marketplace,
        simulate=simulate,
    )


def list_publish_tasks(limit: int = 100) -> list[dict[str, Any]]:
    from repositories.publish_repository import list_publish_tasks as repo_list_publish_tasks

    return repo_list_publish_tasks(limit)


def get_publish_task(task_id: int) -> dict[str, Any]:
    from repositories.publish_repository import get_publish_task as repo_get_publish_task

    return repo_get_publish_task(task_id)
