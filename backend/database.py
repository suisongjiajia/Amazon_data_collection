from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse
from uuid import uuid4

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from config import get_db_config

CREATE_TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS collection_task (
        id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        task_no         VARCHAR(64)     NOT NULL,
        source_type     VARCHAR(32)     NOT NULL DEFAULT 'url',
        source_url      VARCHAR(1024)   NOT NULL,
        marketplace     VARCHAR(255)    NULL,
        status          VARCHAR(32)     NOT NULL,
        total_count     INT             NOT NULL DEFAULT 0,
        success_count   INT             NOT NULL DEFAULT 0,
        fail_count      INT             NOT NULL DEFAULT 0,
        error_message   TEXT            NULL,
        started_at      DATETIME        NULL,
        finished_at     DATETIME        NULL,
        created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_collection_task_no (task_no),
        KEY idx_collection_task_status (status),
        KEY idx_collection_task_created_at (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_product_family (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        task_id             BIGINT UNSIGNED NULL,
        family_key          VARCHAR(64)     NOT NULL,
        parent_asin         VARCHAR(32)     NULL,
        marketplace         VARCHAR(255)    NULL,
        source_url          VARCHAR(1024)   NULL,
        title               VARCHAR(1024)   NULL,
        brand               VARCHAR(255)    NULL,
        rating              VARCHAR(64)     NULL,
        review_count        VARCHAR(64)     NULL,
        main_image_url      VARCHAR(1024)   NULL,
        variant_dimensions  JSON            NULL,
        bullet_points       JSON            NULL,
        raw_payload         JSON            NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_raw_product_family_key (family_key),
        KEY idx_raw_product_family_task_id (task_id),
        KEY idx_raw_product_family_marketplace (marketplace),
        KEY idx_raw_product_family_created_at (created_at),
        CONSTRAINT fk_raw_product_family_task FOREIGN KEY (task_id) REFERENCES collection_task (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_product_variant (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        family_id           BIGINT UNSIGNED NOT NULL,
        asin                VARCHAR(32)     NOT NULL,
        parent_asin         VARCHAR(32)     NULL,
        source_url          VARCHAR(1024)   NULL,
        title               VARCHAR(1024)   NULL,
        price_text          VARCHAR(128)    NULL,
        main_image_url      VARCHAR(1024)   NULL,
        size                VARCHAR(128)    NULL,
        color               VARCHAR(128)    NULL,
        variant_attributes  JSON            NULL,
        raw_payload         JSON            NULL,
        snapshot_time       DATETIME        NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_raw_product_variant_asin (asin),
        KEY idx_raw_product_variant_family_id (family_id),
        KEY idx_raw_product_variant_created_at (created_at),
        CONSTRAINT fk_raw_product_variant_family FOREIGN KEY (family_id) REFERENCES raw_product_family (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS selection_pool (
        id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        raw_product_family_id BIGINT UNSIGNED NOT NULL,
        selection_status      VARCHAR(32)     NOT NULL DEFAULT 'reviewing',
        score                 DECIMAL(10, 2)  NULL,
        owner                 VARCHAR(128)    NULL,
        remark                TEXT            NULL,
        created_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_selection_family (raw_product_family_id),
        KEY idx_selection_status (selection_status),
        CONSTRAINT fk_selection_family FOREIGN KEY (raw_product_family_id) REFERENCES raw_product_family (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS selection_variant_scope (
        id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        selection_id           BIGINT UNSIGNED NOT NULL,
        raw_product_variant_id BIGINT UNSIGNED NOT NULL,
        created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_selection_variant_scope (selection_id, raw_product_variant_id),
        KEY idx_selection_variant_scope_variant_id (raw_product_variant_id),
        CONSTRAINT fk_selection_variant_scope_selection FOREIGN KEY (selection_id) REFERENCES selection_pool (id) ON DELETE CASCADE,
        CONSTRAINT fk_selection_variant_scope_variant FOREIGN KEY (raw_product_variant_id) REFERENCES raw_product_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS product_master (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        selection_id        BIGINT UNSIGNED NOT NULL,
        spu_code            VARCHAR(64)     NOT NULL,
        product_name        VARCHAR(512)    NOT NULL,
        brand               VARCHAR(255)    NULL,
        target_marketplace  VARCHAR(255)    NULL,
        product_type        VARCHAR(128)    NULL,
        development_type    VARCHAR(64)     NULL,
        status              VARCHAR(32)     NOT NULL DEFAULT 'draft',
        default_cost        DECIMAL(10, 2)  NULL,
        base_attributes     JSON            NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_product_master_selection (selection_id),
        UNIQUE KEY uk_product_master_spu_code (spu_code),
        KEY idx_product_master_status (status),
        CONSTRAINT fk_product_master_selection FOREIGN KEY (selection_id) REFERENCES selection_pool (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS product_variant (
        id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        product_master_id      BIGINT UNSIGNED NOT NULL,
        raw_product_variant_id BIGINT UNSIGNED NULL,
        sku                    VARCHAR(64)     NOT NULL,
        variant_key            VARCHAR(255)    NULL,
        color                  VARCHAR(128)    NULL,
        size                   VARCHAR(128)    NULL,
        cost_price             DECIMAL(10, 2)  NULL,
        stock_qty              INT             NOT NULL DEFAULT 0,
        variant_attributes     JSON            NULL,
        created_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at             DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_product_variant_sku (sku),
        KEY idx_product_variant_master_id (product_master_id),
        CONSTRAINT fk_product_variant_master FOREIGN KEY (product_master_id) REFERENCES product_master (id),
        CONSTRAINT fk_product_variant_raw_variant FOREIGN KEY (raw_product_variant_id) REFERENCES raw_product_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS listing_draft (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        product_master_id   BIGINT UNSIGNED NOT NULL,
        marketplace         VARCHAR(255)    NOT NULL,
        shop_name           VARCHAR(255)    NOT NULL,
        status              VARCHAR(32)     NOT NULL DEFAULT 'draft',
        title               VARCHAR(1024)   NOT NULL,
        bullet_points       JSON            NULL,
        description         TEXT            NULL,
        search_terms        TEXT            NULL,
        attributes          JSON            NULL,
        current_version_no  INT             NOT NULL DEFAULT 1,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_listing_draft_master_id (product_master_id),
        KEY idx_listing_draft_marketplace (marketplace),
        CONSTRAINT fk_listing_draft_master FOREIGN KEY (product_master_id) REFERENCES product_master (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS listing_draft_variant (
        id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        draft_id                 BIGINT UNSIGNED NOT NULL,
        variant_id               BIGINT UNSIGNED NOT NULL,
        seller_sku               VARCHAR(64)     NOT NULL,
        price                    DECIMAL(10, 2)  NULL,
        quantity                 INT             NOT NULL DEFAULT 0,
        fulfillment_channel      VARCHAR(32)     NOT NULL DEFAULT 'FBM',
        external_product_id      VARCHAR(64)     NULL,
        external_product_id_type VARCHAR(32)     NULL,
        payload                  JSON            NULL,
        created_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at               DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_listing_draft_variant_pair (draft_id, variant_id),
        KEY idx_listing_draft_variant_draft_id (draft_id),
        CONSTRAINT fk_listing_draft_variant_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id),
        CONSTRAINT fk_listing_draft_variant_variant FOREIGN KEY (variant_id) REFERENCES product_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS listing_draft_version (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        draft_id            BIGINT UNSIGNED NOT NULL,
        version_no          INT             NOT NULL,
        title               VARCHAR(1024)   NOT NULL,
        bullet_points       JSON            NULL,
        description         TEXT            NULL,
        search_terms        TEXT            NULL,
        attributes          JSON            NULL,
        change_note         VARCHAR(255)    NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_listing_draft_version (draft_id, version_no),
        CONSTRAINT fk_listing_draft_version_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS publish_task (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        task_no             VARCHAR(64)     NOT NULL,
        shop_name           VARCHAR(255)    NULL,
        marketplace         VARCHAR(255)    NULL,
        submit_type         VARCHAR(32)     NOT NULL DEFAULT 'simulation',
        status              VARCHAR(32)     NOT NULL,
        total_count         INT             NOT NULL DEFAULT 0,
        success_count       INT             NOT NULL DEFAULT 0,
        fail_count          INT             NOT NULL DEFAULT 0,
        error_message       TEXT            NULL,
        submitted_at        DATETIME        NULL,
        finished_at         DATETIME        NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_publish_task_no (task_no),
        KEY idx_publish_task_status (status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS publish_task_item (
        id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        task_id                 BIGINT UNSIGNED NOT NULL,
        draft_id                BIGINT UNSIGNED NOT NULL,
        draft_variant_id        BIGINT UNSIGNED NOT NULL,
        variant_id              BIGINT UNSIGNED NOT NULL,
        seller_sku              VARCHAR(64)     NOT NULL,
        amazon_submission_id    VARCHAR(128)    NULL,
        status                  VARCHAR(32)     NOT NULL,
        error_code              VARCHAR(64)     NULL,
        error_message           TEXT            NULL,
        issues                  JSON            NULL,
        submission_payload      JSON            NULL,
        retried_times           INT             NOT NULL DEFAULT 0,
        created_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at              DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_publish_task_item_task_id (task_id),
        KEY idx_publish_task_item_status (status),
        CONSTRAINT fk_publish_task_item_task FOREIGN KEY (task_id) REFERENCES publish_task (id),
        CONSTRAINT fk_publish_task_item_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id),
        CONSTRAINT fk_publish_task_item_draft_variant FOREIGN KEY (draft_variant_id) REFERENCES listing_draft_variant (id),
        CONSTRAINT fk_publish_task_item_variant FOREIGN KEY (variant_id) REFERENCES product_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS listing_live (
        id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        publish_task_item_id BIGINT UNSIGNED NULL,
        draft_id             BIGINT UNSIGNED NOT NULL,
        variant_id           BIGINT UNSIGNED NOT NULL,
        shop_name            VARCHAR(255)    NOT NULL,
        marketplace          VARCHAR(255)    NOT NULL,
        seller_sku           VARCHAR(64)     NOT NULL,
        asin                 VARCHAR(32)     NULL,
        parent_asin          VARCHAR(32)     NULL,
        listing_status       VARCHAR(32)     NOT NULL,
        price                DECIMAL(10, 2)  NULL,
        quantity             INT             NOT NULL DEFAULT 0,
        live_payload         JSON            NULL,
        last_sync_at         DATETIME        NULL,
        created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_listing_live_shop_sku (shop_name, marketplace, seller_sku),
        KEY idx_listing_live_status (listing_status),
        CONSTRAINT fk_listing_live_publish_task_item FOREIGN KEY (publish_task_item_id) REFERENCES publish_task_item (id),
        CONSTRAINT fk_listing_live_draft FOREIGN KEY (draft_id) REFERENCES listing_draft (id),
        CONSTRAINT fk_listing_live_variant FOREIGN KEY (variant_id) REFERENCES product_variant (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]

DROP_TABLES = [
    "listing_live",
    "publish_task_item",
    "publish_task",
    "listing_draft_version",
    "listing_draft_variant",
    "listing_draft",
    "product_variant",
    "product_master",
    "selection_variant_scope",
    "selection_pool",
    "raw_product_variant",
    "raw_product_family",
    "raw_product_snapshot",
    "collection_task",
]

JSON_FIELDS = {
    "variant_dimensions",
    "variant_attributes",
    "bullet_points",
    "raw_payload",
    "base_attributes",
    "attributes",
    "payload",
    "issues",
    "submission_payload",
    "live_payload",
}


@contextmanager
def get_connection(*, dict_cursor: bool = False) -> Iterator[Connection]:
    connect_args = dict(get_db_config())
    if dict_cursor:
        connect_args["cursorclass"] = DictCursor

    connection = pymysql.connect(**connect_args)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for statement in CREATE_TABLE_STATEMENTS:
                cursor.execute(statement)


def reset_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table_name in DROP_TABLES:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            for statement in CREATE_TABLE_STATEMENTS:
                cursor.execute(statement)


def check_db() -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    return True


def create_collection_task(source_url: str, source_type: str = "url") -> dict[str, Any]:
    task_no = _build_code("COLL")
    marketplace = _extract_marketplace(source_url)

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
    record = _fetch_one(
        "SELECT * FROM collection_task WHERE id = %s",
        (task_id,),
    )
    if record is None:
        raise ValueError(f"Collection task {task_id} was not found")
    return record


def list_collection_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return _fetch_all(
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
                    _to_json(family.get("variant_dimensions") or []),
                    _to_json(family.get("bullet_points") or []),
                    _to_json(family.get("raw_payload") or {}),
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
                        _to_json(variant.get("variant_attributes") or {}),
                        _to_json(variant.get("raw_payload") or {}),
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
    records = _fetch_all(
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
    records = _fetch_all(
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
    records = _fetch_all(
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
    variants = _fetch_all(
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


def list_listing_live(limit: int = 100) -> list[dict[str, Any]]:
    return _fetch_all(
        "SELECT * FROM listing_live ORDER BY updated_at DESC LIMIT %s",
        (limit,),
    )


def _build_publish_payload(
    draft: dict[str, Any],
    draft_variant: dict[str, Any],
    shop_name: str,
    marketplace: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    title = draft.get("title")
    seller_sku = draft_variant.get("seller_sku")
    price = draft_variant.get("price")

    if not title:
        issues.append({"field": "title", "message": "Title is required before publishing"})
    if not seller_sku:
        issues.append({"field": "seller_sku", "message": "Seller SKU is required before publishing"})
    if price in (None, 0):
        issues.append({"field": "price", "message": "Price must be set before publishing"})

    payload = {
        "shop_name": shop_name,
        "marketplace": marketplace,
        "draft_id": draft["id"],
        "variant_id": draft_variant["variant_id"],
        "seller_sku": seller_sku,
        "title": title,
        "bullet_points": draft.get("bullet_points") or [],
        "description": draft.get("description"),
        "search_terms": draft.get("search_terms"),
        "attributes": draft.get("attributes") or {},
        "price": price,
        "quantity": draft_variant.get("quantity", 0),
        "fulfillment_channel": draft_variant.get("fulfillment_channel"),
        "external_product_id": draft_variant.get("external_product_id"),
        "external_product_id_type": draft_variant.get("external_product_id_type"),
    }
    return payload, issues


def _build_live_listing_record(
    publish_task_item_id: int,
    draft: dict[str, Any],
    draft_variant: dict[str, Any],
    shop_name: str,
    marketplace: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    draft_attributes = draft.get("attributes") or {}
    reference_asin = draft_attributes.get("reference_asin")
    reference_parent_asin = draft_attributes.get("reference_parent_asin")
    if isinstance(reference_asin, str):
        reference_asin = reference_asin.strip() or None
    else:
        reference_asin = None
    if isinstance(reference_parent_asin, str):
        reference_parent_asin = reference_parent_asin.strip() or None
    else:
        reference_parent_asin = None

    return {
        "publish_task_item_id": publish_task_item_id,
        "draft_id": draft["id"],
        "variant_id": draft_variant["variant_id"],
        "shop_name": shop_name,
        "marketplace": marketplace,
        "seller_sku": draft_variant["seller_sku"],
        "asin": reference_asin,
        "parent_asin": reference_parent_asin,
        "listing_status": "published",
        "price": draft_variant.get("price"),
        "quantity": draft_variant.get("quantity", 0),
        "live_payload": payload,
        "last_sync_at": datetime.now(),
    }


def _fetch_one(query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    with get_connection(dict_cursor=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
    if row is None:
        return None
    return _normalize_row(row)


def _fetch_all(query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with get_connection(dict_cursor=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
    return [_normalize_row(row) for row in rows]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key, value in list(normalized.items()):
        if key in JSON_FIELDS and value is not None:
            normalized[key] = _from_json(value)
        elif isinstance(value, datetime):
            normalized[key] = value.isoformat()
        elif isinstance(value, Decimal):
            normalized[key] = float(value)
    return normalized


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _from_json(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _build_code(prefix: str) -> str:
    return f"{prefix}-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}"


def _extract_marketplace(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.hostname


def _build_variant_key(
    variant_attributes: dict[str, Any] | None = None,
    variant_dimensions: Iterable[str] | None = None,
    *,
    color: str | None = None,
    size: str | None = None,
) -> str | None:
    attributes = {str(key): str(value) for key, value in (variant_attributes or {}).items() if value}
    ordered_parts: list[str] = []
    seen_values: set[str] = set()

    for dimension in variant_dimensions or []:
        value = _find_variant_attribute_value(attributes, str(dimension))
        if value and value not in seen_values:
            ordered_parts.append(f"{dimension}: {value}")
            seen_values.add(value)

    if not ordered_parts:
        for key, value in attributes.items():
            if value not in seen_values:
                ordered_parts.append(f"{key}: {value}")
                seen_values.add(value)

    if not ordered_parts:
        for part in (color, size):
            if part and part not in seen_values:
                ordered_parts.append(part)
                seen_values.add(part)

    return " / ".join(ordered_parts) if ordered_parts else None


def _find_variant_attribute_value(attributes: dict[str, str], dimension: str) -> str | None:
    normalized_dimension = _normalize_dimension_key(dimension)
    for key, value in attributes.items():
        if _normalize_dimension_key(key) == normalized_dimension:
            return value
    return None


def _normalize_dimension_key(value: str) -> str:
    return " ".join(value.lower().replace("_", " ").split())
