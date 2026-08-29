from __future__ import annotations

from datetime import datetime
from typing import Any

from db.connection import get_connection
from db.helpers import build_code
from db.serialization import fetch_all, fetch_one, to_json


def create_ozon_collection_task(
    strategy_type: str,
    strategy_params: dict[str, Any],
    *,
    source_url: str = "",
) -> dict[str, Any]:
    task_no = build_code("OZON")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_task (
                    task_no,
                    source_type,
                    source_url,
                    marketplace,
                    platform,
                    strategy_type,
                    strategy_params,
                    status,
                    started_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_no,
                    strategy_type,
                    source_url or f"ozon:{strategy_type}",
                    "ozon.ru",
                    "ozon",
                    strategy_type,
                    to_json(strategy_params),
                    "running",
                    datetime.now(),
                ),
            )
            task_id = cursor.lastrowid
    return get_collection_task(task_id)


def get_collection_task(task_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM collection_task WHERE id = %s", (task_id,))
    if record is None:
        raise ValueError(f"Collection task {task_id} was not found")
    return record


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


def list_ozon_collection_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM collection_task
        WHERE platform = 'ozon'
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def save_ozon_products(task_id: int, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    family_ids: list[int] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for product in products:
                family_key = f"ozon:{product['external_id']}"
                cursor.execute(
                    """
                    INSERT INTO raw_product_family (
                        task_id,
                        family_key,
                        marketplace,
                        platform,
                        external_id,
                        source_url,
                        title,
                        brand,
                        rating,
                        review_count,
                        main_image_url,
                        sales_rank,
                        category_id,
                        type_id,
                        category_name,
                        hot_score,
                        variant_dimensions,
                        bullet_points,
                        raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        task_id = VALUES(task_id),
                        title = COALESCE(VALUES(title), title),
                        brand = COALESCE(VALUES(brand), brand),
                        rating = COALESCE(VALUES(rating), rating),
                        review_count = COALESCE(VALUES(review_count), review_count),
                        main_image_url = COALESCE(VALUES(main_image_url), main_image_url),
                        sales_rank = COALESCE(VALUES(sales_rank), sales_rank),
                        category_id = COALESCE(VALUES(category_id), category_id),
                        type_id = COALESCE(VALUES(type_id), type_id),
                        category_name = COALESCE(VALUES(category_name), category_name),
                        hot_score = COALESCE(VALUES(hot_score), hot_score),
                        raw_payload = VALUES(raw_payload),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        task_id,
                        family_key,
                        "ozon.ru",
                        "ozon",
                        product["external_id"],
                        product.get("source_url"),
                        product.get("title"),
                        product.get("brand"),
                        product.get("rating"),
                        product.get("review_count"),
                        product.get("main_image_url"),
                        product.get("sales_rank"),
                        product.get("category_id"),
                        product.get("type_id"),
                        product.get("category_name"),
                        product.get("hot_score"),
                        to_json(product.get("variant_dimensions") or []),
                        to_json(product.get("bullet_points") or []),
                        to_json(product.get("raw_payload") or {}),
                    ),
                )
                cursor.execute(
                    "SELECT id FROM raw_product_family WHERE family_key = %s",
                    (family_key,),
                )
                family_row = cursor.fetchone()
                family_id = int(family_row[0])

                for variant in product.get("variants") or []:
                    asin = variant.get("external_id") or f"{family_key}-default"
                    cursor.execute(
                        """
                        INSERT INTO raw_product_variant (
                            family_id,
                            asin,
                            external_id,
                            source_url,
                            title,
                            price_text,
                            main_image_url,
                            variant_attributes,
                            raw_payload,
                            snapshot_time
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            title = COALESCE(VALUES(title), title),
                            price_text = COALESCE(VALUES(price_text), price_text),
                            main_image_url = COALESCE(VALUES(main_image_url), main_image_url),
                            variant_attributes = VALUES(variant_attributes),
                            raw_payload = VALUES(raw_payload),
                            snapshot_time = VALUES(snapshot_time),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            family_id,
                            asin,
                            variant.get("external_id"),
                            variant.get("source_url"),
                            variant.get("title"),
                            variant.get("price_text"),
                            variant.get("main_image_url"),
                            to_json(variant.get("variant_attributes") or {}),
                            to_json(variant.get("raw_payload") or {}),
                            variant.get("snapshot_time"),
                        ),
                    )

                family_ids.append(family_id)

    return [get_ozon_product_family(family_id) for family_id in family_ids]


def get_ozon_product_family(family_id: int) -> dict[str, Any]:
    family = fetch_one(
        "SELECT * FROM raw_product_family WHERE id = %s AND platform = 'ozon'",
        (family_id,),
    )
    if family is None:
        raise ValueError(f"Ozon product family {family_id} was not found")
    variants = fetch_all(
        "SELECT * FROM raw_product_variant WHERE family_id = %s ORDER BY id",
        (family_id,),
    )
    family["variants"] = variants
    family["variant_count"] = len(variants)
    return family


def list_ozon_product_families(limit: int = 100) -> list[dict[str, Any]]:
    families = fetch_all(
        """
        SELECT rf.*,
               (SELECT COUNT(*) FROM raw_product_variant rv WHERE rv.family_id = rf.id) AS variant_count
        FROM raw_product_family rf
        WHERE rf.platform = 'ozon'
        ORDER BY rf.sales_rank IS NULL, rf.sales_rank, rf.created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    for family in families:
        family["variants"] = fetch_all(
            "SELECT * FROM raw_product_variant WHERE family_id = %s ORDER BY id",
            (family["id"],),
        )
    return families
