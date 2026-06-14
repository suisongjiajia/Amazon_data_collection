from __future__ import annotations

from datetime import datetime
from typing import Any

import database


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
    existing = database._fetch_one(
        "SELECT id FROM product_master WHERE selection_id = %s",
        (selection_id,),
    )
    if existing is not None:
        return get_product(int(existing["id"]))

    selection = database._fetch_one(
        """
        SELECT
            sp.id AS selection_id,
            sp.raw_product_family_id,
            rf.family_key,
            rf.parent_asin,
            rf.marketplace,
            rf.source_url,
            rf.title,
            rf.brand,
            rf.rating,
            rf.review_count,
            rf.main_image_url,
            rf.variant_dimensions,
            rf.bullet_points
        FROM selection_pool sp
        INNER JOIN raw_product_family rf ON rf.id = sp.raw_product_family_id
        WHERE sp.id = %s
        """,
        (selection_id,),
    )
    if selection is None:
        raise ValueError(f"Selection {selection_id} was not found")

    selected_variants = database._fetch_all(
        """
        SELECT
            rv.*
        FROM selection_variant_scope svs
        INNER JOIN raw_product_variant rv ON rv.id = svs.raw_product_variant_id
        WHERE svs.selection_id = %s
        ORDER BY rv.id ASC
        """,
        (selection_id,),
    )
    if not selected_variants:
        raise ValueError(f"Selection {selection_id} has no variants in scope")

    lead_variant = selected_variants[0]
    resolved_spu_code = spu_code or database._build_code("SPU")
    resolved_product_name = product_name or selection["title"] or resolved_spu_code
    resolved_brand = brand or selection["brand"]
    resolved_marketplace = target_marketplace or selection["marketplace"] or "www.amazon.com"
    base_attributes = {
        "family_key": selection["family_key"],
        "reference_asin": lead_variant.get("asin"),
        "reference_parent_asin": selection.get("parent_asin"),
        "source_url": selection["source_url"],
        "reference_price_text": lead_variant.get("price_text"),
        "variant_dimensions": selection.get("variant_dimensions") or [],
        "bullet_points": selection.get("bullet_points") or [],
        "variant_scope_count": len(selected_variants),
    }

    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO product_master (
                    selection_id,
                    spu_code,
                    product_name,
                    brand,
                    target_marketplace,
                    status,
                    default_cost,
                    base_attributes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    selection_id,
                    resolved_spu_code,
                    resolved_product_name,
                    resolved_brand,
                    resolved_marketplace,
                    "draft",
                    default_cost,
                    database._to_json(base_attributes),
                ),
            )
            product_id = int(cursor.lastrowid)

            for raw_variant in selected_variants:
                cursor.execute(
                    """
                    INSERT INTO product_variant (
                        product_master_id,
                        raw_product_variant_id,
                        sku,
                        variant_key,
                        color,
                        size,
                        cost_price,
                        stock_qty,
                        variant_attributes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        product_id,
                        raw_variant["id"],
                        database._build_code("SKU"),
                        database._build_variant_key(
                            raw_variant.get("variant_attributes"),
                            selection.get("variant_dimensions") or [],
                            color=raw_variant.get("color"),
                            size=raw_variant.get("size"),
                        ),
                        raw_variant.get("color"),
                        raw_variant.get("size"),
                        default_cost,
                        stock_qty,
                        database._to_json(raw_variant.get("variant_attributes") or {}),
                    ),
                )

            cursor.execute(
                """
                UPDATE selection_pool
                SET selection_status = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                ("converted", datetime.now(), selection_id),
            )

    return get_product(product_id)


def list_products(limit: int = 100) -> list[dict[str, Any]]:
    parents = database._fetch_all(
        """
        SELECT
            pm.*,
            sp.raw_product_family_id,
            rf.title AS family_title,
            rf.main_image_url AS family_main_image_url,
            rf.variant_dimensions,
            (
                SELECT COUNT(*)
                FROM product_variant pv
                WHERE pv.product_master_id = pm.id
            ) AS variant_count
        FROM product_master pm
        INNER JOIN selection_pool sp ON sp.id = pm.selection_id
        INNER JOIN raw_product_family rf ON rf.id = sp.raw_product_family_id
        ORDER BY pm.updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return attach_product_variants(parents)


def get_product(product_id: int) -> dict[str, Any]:
    record = database._fetch_one(
        """
        SELECT
            pm.*,
            sp.raw_product_family_id,
            rf.title AS family_title,
            rf.main_image_url AS family_main_image_url,
            rf.variant_dimensions,
            (
                SELECT COUNT(*)
                FROM product_variant pv
                WHERE pv.product_master_id = pm.id
            ) AS variant_count
        FROM product_master pm
        INNER JOIN selection_pool sp ON sp.id = pm.selection_id
        INNER JOIN raw_product_family rf ON rf.id = sp.raw_product_family_id
        WHERE pm.id = %s
        """,
        (product_id,),
    )
    if record is None:
        raise ValueError(f"Product master {product_id} was not found")
    return attach_product_variants([record])[0]


def attach_product_variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    product_ids = [record["id"] for record in records]
    placeholders = ", ".join(["%s"] * len(product_ids))
    variants = database._fetch_all(
        f"""
        SELECT
            pv.*,
            rv.asin AS raw_asin,
            rv.source_url AS raw_source_url,
            rv.price_text AS raw_price_text
        FROM product_variant pv
        LEFT JOIN raw_product_variant rv ON rv.id = pv.raw_product_variant_id
        WHERE pv.product_master_id IN ({placeholders})
        ORDER BY pv.id ASC
        """,
        tuple(product_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {int(record["id"]): [] for record in records}
    for variant in variants:
        grouped[int(variant["product_master_id"])].append(variant)

    for record in records:
        record["variants"] = grouped[int(record["id"])]
    return records
