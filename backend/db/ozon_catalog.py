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
        WHERE platform IN ('ozon', '1688')
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
                        category_id = IF(
                            VALUES(type_id) IS NOT NULL AND VALUES(type_id) != '',
                            VALUES(category_id),
                            category_id
                        ),
                        type_id = COALESCE(NULLIF(VALUES(type_id), ''), type_id),
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
                    external_id = str(variant.get("external_id") or f"{family_key}-default")
                    # asin 全局唯一。同一 SKU 既是自己的商品、又是别的商品的兄弟规格时，
                    # 不能共用一个 asin，否则这条商品会没有变体，列表价格变成空。
                    cursor.execute(
                        """
                        SELECT id FROM raw_product_variant
                        WHERE family_id = %s AND external_id = %s
                        """,
                        (family_id, external_id),
                    )
                    existing = cursor.fetchone()
                    asin = f"{family_id}:{external_id}"[:32]
                    if existing:
                        cursor.execute(
                            """
                            UPDATE raw_product_variant
                            SET source_url = COALESCE(%s, source_url),
                                title = COALESCE(%s, title),
                                price_text = COALESCE(%s, price_text),
                                main_image_url = COALESCE(%s, main_image_url),
                                variant_attributes = %s,
                                raw_payload = %s,
                                snapshot_time = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                            """,
                            (
                                variant.get("source_url"),
                                variant.get("title"),
                                variant.get("price_text"),
                                variant.get("main_image_url"),
                                to_json(variant.get("variant_attributes") or {}),
                                to_json(variant.get("raw_payload") or {}),
                                variant.get("snapshot_time"),
                                existing[0],
                            ),
                        )
                        continue
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
                        """,
                        (
                            family_id,
                            asin,
                            external_id,
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
        "SELECT * FROM raw_product_family WHERE id = %s",
        (family_id,),
    )
    if family is None:
        raise ValueError(f"Product family {family_id} was not found")
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
        WHERE rf.platform IN ('ozon', '1688')
        ORDER BY rf.created_at DESC, rf.sales_rank IS NULL, rf.sales_rank
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


def list_ozon_product_families_by_task(task_id: int, limit: int = 200) -> list[dict[str, Any]]:
    families = fetch_all(
        """
        SELECT rf.*,
               (SELECT COUNT(*) FROM raw_product_variant rv WHERE rv.family_id = rf.id) AS variant_count
        FROM raw_product_family rf
        WHERE rf.task_id = %s
          AND rf.platform IN ('ozon', '1688')
        ORDER BY rf.sales_rank IS NULL, rf.sales_rank, rf.id
        LIMIT %s
        """,
        (task_id, limit),
    )
    for family in families:
        family["variants"] = fetch_all(
            "SELECT * FROM raw_product_variant WHERE family_id = %s ORDER BY id",
            (family["id"],),
        )
    return families


def repair_missing_ozon_variants() -> int:
    """给没有当前货号变体、但详情里已经有价格的商品补一条记录。"""
    families = fetch_all(
        """
        SELECT rf.id, rf.external_id, rf.source_url, rf.title, rf.main_image_url, rf.raw_payload
        FROM raw_product_family rf
        WHERE rf.platform = 'ozon'
          AND rf.external_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM raw_product_variant rv
              WHERE rv.family_id = rf.id AND rv.external_id = rf.external_id
          )
        """,
        (),
    )
    inserted = 0
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for family in families:
                payload = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
                details: dict[str, Any] = {}
                nested = payload.get("rawPayload") if isinstance(payload.get("rawPayload"), dict) else {}
                if isinstance(nested.get("details"), dict):
                    details = nested["details"]
                elif isinstance(payload.get("details"), dict):
                    details = payload["details"]
                price = details.get("price")
                price_text = (
                    f"{int(price)} ₽"
                    if isinstance(price, (int, float)) and not isinstance(price, bool)
                    else None
                )
                external_id = str(family["external_id"])
                cursor.execute(
                    """
                    INSERT INTO raw_product_variant (
                        family_id, asin, external_id, source_url, title, price_text, main_image_url
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        family["id"],
                        f"{family['id']}:{external_id}"[:32],
                        external_id,
                        family.get("source_url"),
                        family.get("title"),
                        price_text,
                        family.get("main_image_url"),
                    ),
                )
                inserted += 1
    return inserted
