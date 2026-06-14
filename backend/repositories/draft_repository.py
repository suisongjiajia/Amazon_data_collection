from __future__ import annotations

from datetime import datetime
from typing import Any

import database
from repositories.product_repository import get_product


def create_listing_draft(
    product_master_id: int,
    *,
    shop_name: str,
    marketplace: str | None = None,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
) -> dict[str, Any]:
    product = get_product(product_master_id)
    base_attributes = product.get("base_attributes") or {}
    draft_marketplace = marketplace or product.get("target_marketplace") or "www.amazon.com"
    draft_title = title or product["product_name"]
    bullet_points = base_attributes.get("bullet_points") or []
    description = f"Draft created from {product['spu_code']}"

    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO listing_draft (
                    product_master_id,
                    marketplace,
                    shop_name,
                    status,
                    title,
                    bullet_points,
                    description,
                    search_terms,
                    attributes,
                    current_version_no
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    product_master_id,
                    draft_marketplace,
                    shop_name,
                    "draft",
                    draft_title,
                    database._to_json(bullet_points),
                    description,
                    "",
                    database._to_json(base_attributes),
                    1,
                ),
            )
            draft_id = cursor.lastrowid

            for variant in product["variants"]:
                resolved_price = price
                if resolved_price is None and variant.get("cost_price"):
                    resolved_price = round(float(variant["cost_price"]) * 2, 2)

                cursor.execute(
                    """
                    INSERT INTO listing_draft_variant (
                        draft_id,
                        variant_id,
                        seller_sku,
                        price,
                        quantity,
                        fulfillment_channel,
                        external_product_id,
                        external_product_id_type,
                        payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        draft_id,
                        variant["id"],
                        variant["sku"],
                        resolved_price,
                        quantity if quantity is not None else variant.get("stock_qty", 0),
                        "FBM",
                        None,
                        None,
                        database._to_json(
                            {
                                "seller_sku": variant["sku"],
                                "marketplace": draft_marketplace,
                                "shop_name": shop_name,
                            }
                        ),
                    ),
                )

            cursor.execute(
                """
                INSERT INTO listing_draft_version (
                    draft_id,
                    version_no,
                    title,
                    bullet_points,
                    description,
                    search_terms,
                    attributes,
                    change_note
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    draft_id,
                    1,
                    draft_title,
                    database._to_json(bullet_points),
                    description,
                    "",
                    database._to_json(base_attributes),
                    "Initial draft",
                ),
            )

    return get_listing_draft(draft_id)


def list_listing_drafts(limit: int = 100) -> list[dict[str, Any]]:
    parents = database._fetch_all(
        """
        SELECT ld.*, pm.product_name, pm.spu_code
        FROM listing_draft ld
        INNER JOIN product_master pm ON pm.id = ld.product_master_id
        ORDER BY ld.updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return attach_draft_variants(parents)


def get_listing_draft(draft_id: int) -> dict[str, Any]:
    record = database._fetch_one(
        """
        SELECT ld.*, pm.product_name, pm.spu_code
        FROM listing_draft ld
        INNER JOIN product_master pm ON pm.id = ld.product_master_id
        WHERE ld.id = %s
        """,
        (draft_id,),
    )
    if record is None:
        raise ValueError(f"Listing draft {draft_id} was not found")
    return attach_draft_variants([record])[0]


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
    current = get_listing_draft(draft_id)
    next_version = int(current["current_version_no"]) + 1
    merged_title = title if title is not None else current["title"]
    merged_bullets = bullet_points if bullet_points is not None else current.get("bullet_points") or []
    merged_description = description if description is not None else current.get("description")
    merged_search_terms = search_terms if search_terms is not None else current.get("search_terms")
    merged_attributes = attributes if attributes is not None else current.get("attributes") or {}
    merged_status = status if status is not None else current["status"]

    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE listing_draft
                SET title = %s,
                    bullet_points = %s,
                    description = %s,
                    search_terms = %s,
                    attributes = %s,
                    status = %s,
                    current_version_no = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    merged_title,
                    database._to_json(merged_bullets),
                    merged_description,
                    merged_search_terms,
                    database._to_json(merged_attributes),
                    merged_status,
                    next_version,
                    datetime.now(),
                    draft_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO listing_draft_version (
                    draft_id,
                    version_no,
                    title,
                    bullet_points,
                    description,
                    search_terms,
                    attributes,
                    change_note
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    draft_id,
                    next_version,
                    merged_title,
                    database._to_json(merged_bullets),
                    merged_description,
                    merged_search_terms,
                    database._to_json(merged_attributes),
                    change_note or "Draft updated",
                ),
            )

    return get_listing_draft(draft_id)


def update_listing_draft_variant(
    draft_variant_id: int,
    *,
    price: float | None = None,
    quantity: int | None = None,
    fulfillment_channel: str | None = None,
    external_product_id: str | None = None,
    external_product_id_type: str | None = None,
) -> dict[str, Any]:
    current = database._fetch_one(
        "SELECT * FROM listing_draft_variant WHERE id = %s",
        (draft_variant_id,),
    )
    if current is None:
        raise ValueError(f"Listing draft variant {draft_variant_id} was not found")

    payload = current.get("payload") or {}
    payload.update(
        {
            "price": price if price is not None else current.get("price"),
            "quantity": quantity if quantity is not None else current.get("quantity"),
            "fulfillment_channel": fulfillment_channel or current.get("fulfillment_channel"),
            "external_product_id": external_product_id
            if external_product_id is not None
            else current.get("external_product_id"),
            "external_product_id_type": external_product_id_type
            if external_product_id_type is not None
            else current.get("external_product_id_type"),
        }
    )

    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE listing_draft_variant
                SET price = %s,
                    quantity = %s,
                    fulfillment_channel = %s,
                    external_product_id = %s,
                    external_product_id_type = %s,
                    payload = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                (
                    price if price is not None else current.get("price"),
                    quantity if quantity is not None else current.get("quantity"),
                    fulfillment_channel or current.get("fulfillment_channel"),
                    external_product_id
                    if external_product_id is not None
                    else current.get("external_product_id"),
                    external_product_id_type
                    if external_product_id_type is not None
                    else current.get("external_product_id_type"),
                    database._to_json(payload),
                    datetime.now(),
                    draft_variant_id,
                ),
            )

    updated = database._fetch_one(
        "SELECT * FROM listing_draft_variant WHERE id = %s",
        (draft_variant_id,),
    )
    if updated is None:
        raise ValueError(f"Listing draft variant {draft_variant_id} was not found")
    return updated


def attach_draft_variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    draft_ids = [record["id"] for record in records]
    placeholders = ", ".join(["%s"] * len(draft_ids))
    variants = database._fetch_all(
        f"""
        SELECT ldv.*, pv.variant_key, pv.color, pv.size
        FROM listing_draft_variant ldv
        INNER JOIN product_variant pv ON pv.id = ldv.variant_id
        WHERE ldv.draft_id IN ({placeholders})
        ORDER BY ldv.id ASC
        """,
        tuple(draft_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {int(record["id"]): [] for record in records}
    for variant in variants:
        grouped[int(variant["draft_id"])].append(variant)

    for record in records:
        record["variants"] = grouped[int(record["id"])]
    return records
