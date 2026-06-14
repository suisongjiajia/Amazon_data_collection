from __future__ import annotations

from datetime import datetime
from typing import Any

import database


def create_selection(
    raw_product_family_id: int,
    *,
    owner: str | None = None,
    remark: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    family = database._fetch_one(
        "SELECT * FROM raw_product_family WHERE id = %s",
        (raw_product_family_id,),
    )
    if family is None:
        raise ValueError(f"Raw product family {raw_product_family_id} was not found")

    existing = database._fetch_one(
        "SELECT * FROM selection_pool WHERE raw_product_family_id = %s",
        (raw_product_family_id,),
    )
    if existing is not None:
        with database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE selection_pool
                    SET owner = COALESCE(%s, owner),
                        remark = COALESCE(%s, remark),
                        score = COALESCE(%s, score),
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (owner, remark, score, datetime.now(), existing["id"]),
                )
        return get_selection(int(existing["id"]))

    variant_ids = database._fetch_all(
        "SELECT id FROM raw_product_variant WHERE family_id = %s ORDER BY id ASC",
        (raw_product_family_id,),
    )
    if not variant_ids:
        raise ValueError(f"Raw product family {raw_product_family_id} has no variants")

    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO selection_pool (raw_product_family_id, selection_status, score, owner, remark)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (raw_product_family_id, "reviewing", score, owner, remark),
            )
            selection_id = int(cursor.lastrowid)

            for variant in variant_ids:
                cursor.execute(
                    """
                    INSERT INTO selection_variant_scope (selection_id, raw_product_variant_id)
                    VALUES (%s, %s)
                    """,
                    (selection_id, int(variant["id"])),
                )

    return get_selection(selection_id)


def update_selection_variant_scope(
    selection_id: int,
    raw_product_variant_ids: list[int],
) -> dict[str, Any]:
    selection = database._fetch_one(
        "SELECT raw_product_family_id FROM selection_pool WHERE id = %s",
        (selection_id,),
    )
    if selection is None:
        raise ValueError(f"Selection {selection_id} was not found")

    if not raw_product_variant_ids:
        raise ValueError("At least one variant must remain in selection scope")

    placeholders = ", ".join(["%s"] * len(raw_product_variant_ids))
    variants = database._fetch_all(
        f"""
        SELECT id
        FROM raw_product_variant
        WHERE family_id = %s AND id IN ({placeholders})
        """,
        (selection["raw_product_family_id"], *raw_product_variant_ids),
    )
    valid_ids = {int(item["id"]) for item in variants}
    expected_ids = set(raw_product_variant_ids)
    if valid_ids != expected_ids:
        raise ValueError("Selection scope contains variants outside the selected family")

    with database.get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM selection_variant_scope WHERE selection_id = %s",
                (selection_id,),
            )
            for variant_id in raw_product_variant_ids:
                cursor.execute(
                    """
                    INSERT INTO selection_variant_scope (selection_id, raw_product_variant_id)
                    VALUES (%s, %s)
                    """,
                    (selection_id, variant_id),
                )
            cursor.execute(
                """
                UPDATE selection_pool
                SET updated_at = %s
                WHERE id = %s
                """,
                (datetime.now(), selection_id),
            )

    return get_selection(selection_id)


def list_selections(limit: int = 100) -> list[dict[str, Any]]:
    records = database._fetch_all(
        """
        SELECT
            sp.*,
            rf.family_key,
            rf.parent_asin AS family_parent_asin,
            rf.marketplace AS family_marketplace,
            rf.source_url AS family_source_url,
            rf.title AS family_title,
            rf.brand AS family_brand,
            rf.rating AS family_rating,
            rf.review_count AS family_review_count,
            rf.main_image_url AS family_main_image_url,
            rf.variant_dimensions,
            (
                SELECT COUNT(*)
                FROM raw_product_variant rv
                WHERE rv.family_id = rf.id
            ) AS family_variant_count,
            (
                SELECT COUNT(*)
                FROM selection_variant_scope svs
                WHERE svs.selection_id = sp.id
            ) AS selected_variant_count
        FROM selection_pool sp
        INNER JOIN raw_product_family rf ON rf.id = sp.raw_product_family_id
        ORDER BY sp.updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return attach_selection_variants(records)


def get_selection(selection_id: int) -> dict[str, Any]:
    record = database._fetch_one(
        """
        SELECT
            sp.*,
            rf.family_key,
            rf.parent_asin AS family_parent_asin,
            rf.marketplace AS family_marketplace,
            rf.source_url AS family_source_url,
            rf.title AS family_title,
            rf.brand AS family_brand,
            rf.rating AS family_rating,
            rf.review_count AS family_review_count,
            rf.main_image_url AS family_main_image_url,
            rf.variant_dimensions,
            (
                SELECT COUNT(*)
                FROM raw_product_variant rv
                WHERE rv.family_id = rf.id
            ) AS family_variant_count,
            (
                SELECT COUNT(*)
                FROM selection_variant_scope svs
                WHERE svs.selection_id = sp.id
            ) AS selected_variant_count
        FROM selection_pool sp
        INNER JOIN raw_product_family rf ON rf.id = sp.raw_product_family_id
        WHERE sp.id = %s
        """,
        (selection_id,),
    )
    if record is None:
        raise ValueError(f"Selection {selection_id} was not found")
    return attach_selection_variants([record])[0]


def attach_selection_variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    selection_ids = [int(record["id"]) for record in records]
    placeholders = ", ".join(["%s"] * len(selection_ids))
    variants = database._fetch_all(
        f"""
        SELECT
            svs.selection_id,
            rv.*
        FROM selection_variant_scope svs
        INNER JOIN raw_product_variant rv ON rv.id = svs.raw_product_variant_id
        WHERE svs.selection_id IN ({placeholders})
        ORDER BY rv.id ASC
        """,
        tuple(selection_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {selection_id: [] for selection_id in selection_ids}
    for variant in variants:
        grouped[int(variant["selection_id"])].append(variant)

    for record in records:
        record["variants"] = grouped[int(record["id"])]
    return records
