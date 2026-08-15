from __future__ import annotations

from datetime import datetime
from typing import Any

from db.connection import get_connection
from db.helpers import build_code, extract_marketplace
from db.serialization import fetch_all, fetch_one, to_json


def create_collection_task(source_url: str, source_type: str = "url") -> dict[str, Any]:
    task_no = build_code("COLL")
    marketplace = extract_marketplace(source_url)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_task (
                    task_no, source_type, source_url, marketplace, status, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (task_no, source_type, source_url, marketplace, "running", datetime.now()),
            )
            task_id = cursor.lastrowid

    return get_collection_task(task_id)


def finish_collection_task(
    task_id: int,
    *,
    status: str,
    total_count: int,
    success_count: int,
    fail_count: int,
    error_message: str | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE collection_task
                SET status = %s,
                    total_count = %s,
                    success_count = %s,
                    fail_count = %s,
                    error_message = %s,
                    finished_at = %s
                WHERE id = %s
                """,
                (
                    status,
                    total_count,
                    success_count,
                    fail_count,
                    error_message,
                    datetime.now(),
                    task_id,
                ),
            )

    return get_collection_task(task_id)


def get_collection_task(task_id: int) -> dict[str, Any]:
    record = fetch_one(
        "SELECT * FROM collection_task WHERE id = %s",
        (task_id,),
    )
    if record is None:
        raise ValueError(f"Collection task {task_id} was not found")
    return record


def list_collection_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT * FROM collection_task ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def save_raw_product_families(
    task_id: int | None,
    families: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not families:
        return []

    family_ids: list[int] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for family in families:
                cursor.execute(
                    "SELECT id FROM raw_product_family WHERE family_key = %s",
                    (family["family_key"],),
                )
                existing_family = cursor.fetchone()

                family_update_params = (
                    task_id,
                    family.get("parent_asin"),
                    family.get("marketplace"),
                    family.get("source_url"),
                    family.get("title"),
                    family.get("brand"),
                    family.get("rating"),
                    family.get("review_count"),
                    family.get("main_image_url"),
                    to_json(family.get("variant_dimensions") or []),
                    to_json(family.get("bullet_points") or []),
                    to_json(family.get("raw_payload") or {}),
                )

                if existing_family:
                    family_id = int(existing_family[0])
                    cursor.execute(
                        """
                        UPDATE raw_product_family
                        SET task_id = COALESCE(%s, task_id),
                            parent_asin = COALESCE(%s, parent_asin),
                            marketplace = COALESCE(%s, marketplace),
                            source_url = COALESCE(%s, source_url),
                            title = COALESCE(%s, title),
                            brand = COALESCE(%s, brand),
                            rating = COALESCE(%s, rating),
                            review_count = COALESCE(%s, review_count),
                            main_image_url = COALESCE(%s, main_image_url),
                            variant_dimensions = CASE
                                WHEN %s IS NULL OR JSON_LENGTH(%s) = 0 THEN variant_dimensions
                                ELSE %s
                            END,
                            bullet_points = CASE
                                WHEN %s IS NULL OR JSON_LENGTH(%s) = 0 THEN bullet_points
                                ELSE %s
                            END,
                            raw_payload = %s,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (
                            family_update_params[0],
                            family_update_params[1],
                            family_update_params[2],
                            family_update_params[3],
                            family_update_params[4],
                            family_update_params[5],
                            family_update_params[6],
                            family_update_params[7],
                            family_update_params[8],
                            family_update_params[9],
                            family_update_params[9],
                            family_update_params[9],
                            family_update_params[10],
                            family_update_params[10],
                            family_update_params[10],
                            family_update_params[11],
                            datetime.now(),
                            family_id,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO raw_product_family (
                            task_id,
                            family_key,
                            parent_asin,
                            marketplace,
                            source_url,
                            title,
                            brand,
                            rating,
                            review_count,
                            main_image_url,
                            variant_dimensions,
                            bullet_points,
                            raw_payload
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (task_id, family["family_key"]) + family_update_params[1:],
                    )
                    family_id = int(cursor.lastrowid)

                family_ids.append(family_id)
                current_variant_asins: list[str] = []
                for variant in family.get("variants") or []:
                    asin = variant.get("asin")
                    if not asin:
                        continue
                    current_variant_asins.append(str(asin).strip().upper())

                    cursor.execute(
                        "SELECT id FROM raw_product_variant WHERE asin = %s",
                        (asin,),
                    )
                    existing_variant = cursor.fetchone()
                    variant_params = (
                        family_id,
                        asin,
                        variant.get("parent_asin"),
                        variant.get("source_url"),
                        variant.get("title"),
                        variant.get("price_text"),
                        variant.get("main_image_url"),
                        variant.get("size"),
                        variant.get("color"),
                        to_json(variant.get("variant_attributes") or {}),
                        to_json(variant.get("raw_payload") or {}),
                        variant.get("snapshot_time"),
                    )

                    if existing_variant:
                        cursor.execute(
                            """
                            UPDATE raw_product_variant
                            SET family_id = %s,
                                asin = %s,
                                parent_asin = COALESCE(%s, parent_asin),
                                source_url = COALESCE(%s, source_url),
                                title = COALESCE(%s, title),
                                price_text = COALESCE(%s, price_text),
                                main_image_url = COALESCE(%s, main_image_url),
                                size = COALESCE(%s, size),
                                color = COALESCE(%s, color),
                                variant_attributes = CASE
                                    WHEN %s IS NULL OR JSON_LENGTH(%s) = 0 THEN variant_attributes
                                    ELSE %s
                                END,
                                raw_payload = %s,
                                snapshot_time = COALESCE(%s, snapshot_time),
                                updated_at = %s
                            WHERE id = %s
                            """,
                            (
                                variant_params[0],
                                variant_params[1],
                                variant_params[2],
                                variant_params[3],
                                variant_params[4],
                                variant_params[5],
                                variant_params[6],
                                variant_params[7],
                                variant_params[8],
                                variant_params[9],
                                variant_params[9],
                                variant_params[9],
                                variant_params[10],
                                variant_params[11],
                                datetime.now(),
                                int(existing_variant[0]),
                            ),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO raw_product_variant (
                                family_id,
                                asin,
                                parent_asin,
                                source_url,
                                title,
                                price_text,
                                main_image_url,
                                size,
                                color,
                                variant_attributes,
                                raw_payload,
                                snapshot_time
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            variant_params,
                        )

                if current_variant_asins:
                    placeholders = ", ".join(["%s"] * len(current_variant_asins))
                    cursor.execute(
                        f"""
                        DELETE FROM raw_product_variant
                        WHERE family_id = %s
                          AND asin NOT IN ({placeholders})
                        """,
                        (family_id, *current_variant_asins),
                    )

    ordered_ids = list(dict.fromkeys(family_ids))
    return get_raw_product_families(ordered_ids)


def list_raw_product_families(limit: int = 100) -> list[dict[str, Any]]:
    records = fetch_all(
        """
        SELECT
            rf.*,
            sp.id AS selection_id,
            sp.selection_status,
            sp.score AS selection_score,
            sp.owner AS selection_owner,
            sp.remark AS selection_remark,
            pm.id AS product_master_id
        FROM raw_product_family rf
        LEFT JOIN selection_pool sp ON sp.raw_product_family_id = rf.id
        LEFT JOIN product_master pm ON pm.selection_id = sp.id
        ORDER BY rf.updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return attach_raw_variants(records)


def get_raw_product_families_for_task(task_id: int) -> list[dict[str, Any]]:
    records = fetch_all(
        """
        SELECT
            rf.*,
            sp.id AS selection_id,
            sp.selection_status,
            sp.score AS selection_score,
            sp.owner AS selection_owner,
            sp.remark AS selection_remark,
            pm.id AS product_master_id
        FROM raw_product_family rf
        LEFT JOIN selection_pool sp ON sp.raw_product_family_id = rf.id
        LEFT JOIN product_master pm ON pm.selection_id = sp.id
        WHERE rf.task_id = %s
        ORDER BY rf.updated_at DESC
        """,
        (task_id,),
    )
    return attach_raw_variants(records)


def get_raw_product_families(ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []

    placeholders = ", ".join(["%s"] * len(ids))
    records = fetch_all(
        f"""
        SELECT
            rf.*,
            sp.id AS selection_id,
            sp.selection_status,
            sp.score AS selection_score,
            sp.owner AS selection_owner,
            sp.remark AS selection_remark,
            pm.id AS product_master_id
        FROM raw_product_family rf
        LEFT JOIN selection_pool sp ON sp.raw_product_family_id = rf.id
        LEFT JOIN product_master pm ON pm.selection_id = sp.id
        WHERE rf.id IN ({placeholders})
        ORDER BY rf.updated_at DESC
        """,
        tuple(ids),
    )
    attached = attach_raw_variants(records)
    records_by_id = {int(record["id"]): record for record in attached}
    return [records_by_id[item_id] for item_id in ids if item_id in records_by_id]


def get_raw_product_family(family_id: int) -> dict[str, Any]:
    records = get_raw_product_families([family_id])
    if not records:
        raise ValueError(f"Raw product family {family_id} was not found")
    return records[0]


def attach_raw_variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    family_ids = [int(record["id"]) for record in records]
    placeholders = ", ".join(["%s"] * len(family_ids))
    variants = fetch_all(
        f"""
        SELECT *
        FROM raw_product_variant
        WHERE family_id IN ({placeholders})
        ORDER BY id ASC
        """,
        tuple(family_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {family_id: [] for family_id in family_ids}
    for variant in variants:
        grouped[int(variant["family_id"])].append(variant)

    for record in records:
        family_variants = grouped[int(record["id"])]
        record["variants"] = family_variants
        record["variant_count"] = len(family_variants)
    return records


def list_listing_live(limit: int = 100) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT * FROM listing_live ORDER BY updated_at DESC LIMIT %s",
        (limit,),
    )
