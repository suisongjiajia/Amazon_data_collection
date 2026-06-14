from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterator
from urllib.parse import urlparse
from uuid import uuid4

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from collector.models import ProductInfo
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
    CREATE TABLE IF NOT EXISTS raw_product_snapshot (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        task_id             BIGINT UNSIGNED NULL,
        asin                VARCHAR(32)     NULL,
        parent_asin         VARCHAR(32)     NULL,
        marketplace         VARCHAR(255)    NULL,
        source_url          VARCHAR(1024)   NULL,
        title               TEXT            NULL,
        price_text          VARCHAR(128)    NULL,
        rating              VARCHAR(64)     NULL,
        review_count        VARCHAR(64)     NULL,
        main_image_url      VARCHAR(1024)   NULL,
        brand               VARCHAR(255)    NULL,
        size                VARCHAR(128)    NULL,
        color               VARCHAR(128)    NULL,
        variant_attributes  JSON            NULL,
        bullet_points       JSON            NULL,
        raw_payload         JSON            NULL,
        snapshot_time       DATETIME        NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_raw_product_task_id (task_id),
        KEY idx_raw_product_asin (asin),
        KEY idx_raw_product_marketplace (marketplace),
        KEY idx_raw_product_created_at (created_at),
        CONSTRAINT fk_raw_product_task FOREIGN KEY (task_id) REFERENCES collection_task (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS selection_pool (
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        raw_product_id      BIGINT UNSIGNED NOT NULL,
        selection_status    VARCHAR(32)     NOT NULL DEFAULT 'reviewing',
        score               DECIMAL(10, 2)  NULL,
        owner               VARCHAR(128)    NULL,
        remark              TEXT            NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_selection_raw_product (raw_product_id),
        KEY idx_selection_status (selection_status),
        CONSTRAINT fk_selection_raw_product FOREIGN KEY (raw_product_id) REFERENCES raw_product_snapshot (id)
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
        id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        product_master_id   BIGINT UNSIGNED NOT NULL,
        raw_product_id      BIGINT UNSIGNED NULL,
        sku                 VARCHAR(64)     NOT NULL,
        variant_key         VARCHAR(255)    NULL,
        color               VARCHAR(128)    NULL,
        size                VARCHAR(128)    NULL,
        cost_price          DECIMAL(10, 2)  NULL,
        stock_qty           INT             NOT NULL DEFAULT 0,
        variant_attributes  JSON            NULL,
        created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        UNIQUE KEY uk_product_variant_sku (sku),
        KEY idx_product_variant_master_id (product_master_id),
        CONSTRAINT fk_product_variant_master FOREIGN KEY (product_master_id) REFERENCES product_master (id),
        CONSTRAINT fk_product_variant_raw_product FOREIGN KEY (raw_product_id) REFERENCES raw_product_snapshot (id)
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

JSON_FIELDS = {
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


def save_raw_products(task_id: int | None, products: list[ProductInfo]) -> list[dict[str, Any]]:
    if not products:
        return []

    inserted_ids: list[int] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for product in products:
                payload = product.to_dict()
                cursor.execute(
                    """
                    INSERT INTO raw_product_snapshot (
                        task_id,
                        asin,
                        marketplace,
                        source_url,
                        title,
                        price_text,
                        rating,
                        review_count,
                        main_image_url,
                        brand,
                        size,
                        color,
                        variant_attributes,
                        bullet_points,
                        raw_payload,
                        snapshot_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        task_id,
                        product.asin,
                        _extract_marketplace(product.source_url),
                        product.source_url,
                        product.title,
                        product.price,
                        product.rating,
                        product.review_count,
                        product.main_image_url,
                        product.brand,
                        product.size,
                        product.color,
                        _to_json(product.variant_attributes),
                        _to_json(product.bullet_points),
                        _to_json(payload),
                        product.collected_at,
                    ),
                )
                inserted_ids.append(cursor.lastrowid)

    return get_raw_products(inserted_ids)


def save_products(products: list[ProductInfo]) -> list[int]:
    rows = save_raw_products(None, products)
    return [int(row["id"]) for row in rows]


def list_raw_products(limit: int = 100) -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT
            rp.*,
            sp.id AS selection_id,
            sp.selection_status,
            sp.score AS selection_score,
            sp.owner AS selection_owner
        FROM raw_product_snapshot rp
        LEFT JOIN selection_pool sp ON sp.raw_product_id = rp.id
        ORDER BY rp.created_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def get_raw_products_for_task(task_id: int) -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT
            rp.*,
            sp.id AS selection_id,
            sp.selection_status,
            sp.score AS selection_score,
            sp.owner AS selection_owner
        FROM raw_product_snapshot rp
        LEFT JOIN selection_pool sp ON sp.raw_product_id = rp.id
        WHERE rp.task_id = %s
        ORDER BY rp.created_at DESC
        """,
        (task_id,),
    )


def get_raw_products(ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []

    placeholders = ", ".join(["%s"] * len(ids))
    return _fetch_all(
        f"""
        SELECT
            rp.*,
            sp.id AS selection_id,
            sp.selection_status,
            sp.score AS selection_score,
            sp.owner AS selection_owner
        FROM raw_product_snapshot rp
        LEFT JOIN selection_pool sp ON sp.raw_product_id = rp.id
        WHERE rp.id IN ({placeholders})
        ORDER BY rp.created_at DESC
        """,
        tuple(ids),
    )


def create_selection(
    raw_product_id: int,
    *,
    owner: str | None = None,
    remark: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    raw_product = _fetch_one(
        "SELECT * FROM raw_product_snapshot WHERE id = %s",
        (raw_product_id,),
    )
    if raw_product is None:
        raise ValueError(f"Raw product {raw_product_id} was not found")

    existing = _fetch_one(
        "SELECT * FROM selection_pool WHERE raw_product_id = %s",
        (raw_product_id,),
    )
    if existing is not None:
        with get_connection() as connection:
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

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO selection_pool (raw_product_id, selection_status, score, owner, remark)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (raw_product_id, "reviewing", score, owner, remark),
            )
            selection_id = cursor.lastrowid

    return get_selection(selection_id)


def list_selections(limit: int = 100) -> list[dict[str, Any]]:
    return _fetch_all(
        """
        SELECT
            sp.*,
            rp.asin AS raw_asin,
            rp.title AS raw_title,
            rp.price_text AS raw_price_text,
            rp.marketplace AS raw_marketplace,
            rp.main_image_url AS raw_main_image_url,
            rp.source_url AS raw_source_url,
            rp.brand AS raw_brand
        FROM selection_pool sp
        INNER JOIN raw_product_snapshot rp ON rp.id = sp.raw_product_id
        ORDER BY sp.updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )


def get_selection(selection_id: int) -> dict[str, Any]:
    record = _fetch_one(
        """
        SELECT
            sp.*,
            rp.asin AS raw_asin,
            rp.title AS raw_title,
            rp.price_text AS raw_price_text,
            rp.marketplace AS raw_marketplace,
            rp.main_image_url AS raw_main_image_url,
            rp.source_url AS raw_source_url,
            rp.brand AS raw_brand
        FROM selection_pool sp
        INNER JOIN raw_product_snapshot rp ON rp.id = sp.raw_product_id
        WHERE sp.id = %s
        """,
        (selection_id,),
    )
    if record is None:
        raise ValueError(f"Selection {selection_id} was not found")
    return record


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
    existing = _fetch_one(
        "SELECT id FROM product_master WHERE selection_id = %s",
        (selection_id,),
    )
    if existing is not None:
        return get_product(int(existing["id"]))

    selection = _fetch_one(
        """
        SELECT
            sp.id AS selection_id,
            rp.id AS raw_product_id,
            rp.asin,
            rp.marketplace,
            rp.source_url,
            rp.title,
            rp.brand,
            rp.price_text,
            rp.size,
            rp.color,
            rp.variant_attributes,
            rp.bullet_points
        FROM selection_pool sp
        INNER JOIN raw_product_snapshot rp ON rp.id = sp.raw_product_id
        WHERE sp.id = %s
        """,
        (selection_id,),
    )
    if selection is None:
        raise ValueError(f"Selection {selection_id} was not found")

    resolved_spu_code = spu_code or _build_code("SPU")
    resolved_product_name = product_name or selection["title"] or resolved_spu_code
    resolved_brand = brand or selection["brand"]
    resolved_marketplace = target_marketplace or selection["marketplace"] or "www.amazon.com"
    base_attributes = {
        "source_url": selection["source_url"],
        "reference_asin": selection["asin"],
        "reference_price_text": selection["price_text"],
        "variant_attributes": selection["variant_attributes"] or {},
        "bullet_points": selection["bullet_points"] or [],
    }

    with get_connection() as connection:
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
                    _to_json(base_attributes),
                ),
            )
            product_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO product_variant (
                    product_master_id,
                    raw_product_id,
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
                    selection["raw_product_id"],
                    _build_code("SKU"),
                    _build_variant_key(selection["color"], selection["size"]),
                    selection["color"],
                    selection["size"],
                    default_cost,
                    stock_qty,
                    _to_json(selection["variant_attributes"] or {}),
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
    parents = _fetch_all(
        "SELECT * FROM product_master ORDER BY updated_at DESC LIMIT %s",
        (limit,),
    )
    return _attach_product_variants(parents)


def get_product(product_id: int) -> dict[str, Any]:
    record = _fetch_one(
        "SELECT * FROM product_master WHERE id = %s",
        (product_id,),
    )
    if record is None:
        raise ValueError(f"Product master {product_id} was not found")
    return _attach_product_variants([record])[0]


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

    with get_connection() as connection:
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
                    _to_json(bullet_points),
                    description,
                    "",
                    _to_json(base_attributes),
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
                        _to_json(
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
                    _to_json(bullet_points),
                    description,
                    "",
                    _to_json(base_attributes),
                    "Initial draft",
                ),
            )

    return get_listing_draft(draft_id)


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

    with get_connection() as connection:
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
                    _to_json(merged_bullets),
                    merged_description,
                    merged_search_terms,
                    _to_json(merged_attributes),
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
                    _to_json(merged_bullets),
                    merged_description,
                    merged_search_terms,
                    _to_json(merged_attributes),
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
    current = _fetch_one(
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

    with get_connection() as connection:
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
                    _to_json(payload),
                    datetime.now(),
                    draft_variant_id,
                ),
            )

    updated = _fetch_one(
        "SELECT * FROM listing_draft_variant WHERE id = %s",
        (draft_variant_id,),
    )
    if updated is None:
        raise ValueError(f"Listing draft variant {draft_variant_id} was not found")
    return updated


def list_listing_drafts(limit: int = 100) -> list[dict[str, Any]]:
    parents = _fetch_all(
        """
        SELECT ld.*, pm.product_name, pm.spu_code
        FROM listing_draft ld
        INNER JOIN product_master pm ON pm.id = ld.product_master_id
        ORDER BY ld.updated_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return _attach_draft_variants(parents)


def get_listing_draft(draft_id: int) -> dict[str, Any]:
    record = _fetch_one(
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
    return _attach_draft_variants([record])[0]


def create_publish_task(
    draft_ids: list[int],
    *,
    shop_name: str | None = None,
    marketplace: str | None = None,
    simulate: bool = True,
) -> dict[str, Any]:
    if not draft_ids:
        raise ValueError("At least one draft is required")

    drafts = [get_listing_draft(draft_id) for draft_id in draft_ids]
    task_no = _build_code("PUB")
    task_shop_name = shop_name or drafts[0]["shop_name"]
    task_marketplace = marketplace or drafts[0]["marketplace"]

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO publish_task (
                    task_no, shop_name, marketplace, submit_type, status, submitted_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    task_no,
                    task_shop_name,
                    task_marketplace,
                    "simulation" if simulate else "manual",
                    "running",
                    datetime.now(),
                ),
            )
            task_id = cursor.lastrowid

            total_count = 0
            success_count = 0
            fail_count = 0

            for draft in drafts:
                for draft_variant in draft["variants"]:
                    total_count += 1
                    payload, issues = _build_publish_payload(
                        draft,
                        draft_variant,
                        task_shop_name,
                        task_marketplace,
                    )
                    item_status = "success" if not issues and simulate else "failed" if issues else "pending"
                    error_code = "VALIDATION_ERROR" if issues else None
                    error_message = "; ".join(issue["message"] for issue in issues) if issues else None
                    submission_id = _build_code("SIM") if item_status == "success" else None

                    cursor.execute(
                        """
                        INSERT INTO publish_task_item (
                            task_id,
                            draft_id,
                            draft_variant_id,
                            variant_id,
                            seller_sku,
                            amazon_submission_id,
                            status,
                            error_code,
                            error_message,
                            issues,
                            submission_payload
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            task_id,
                            draft["id"],
                            draft_variant["id"],
                            draft_variant["variant_id"],
                            draft_variant["seller_sku"],
                            submission_id,
                            item_status,
                            error_code,
                            error_message,
                            _to_json(issues),
                            _to_json(payload),
                        ),
                    )
                    publish_item_id = cursor.lastrowid

                    if item_status == "success":
                        success_count += 1
                        cursor.execute(
                            """
                            INSERT INTO listing_live (
                                publish_task_item_id,
                                draft_id,
                                variant_id,
                                shop_name,
                                marketplace,
                                seller_sku,
                                asin,
                                parent_asin,
                                listing_status,
                                price,
                                quantity,
                                live_payload,
                                last_sync_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                publish_task_item_id = VALUES(publish_task_item_id),
                                listing_status = VALUES(listing_status),
                                price = VALUES(price),
                                quantity = VALUES(quantity),
                                live_payload = VALUES(live_payload),
                                last_sync_at = VALUES(last_sync_at),
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (
                                publish_item_id,
                                draft["id"],
                                draft_variant["variant_id"],
                                task_shop_name,
                                task_marketplace,
                                draft_variant["seller_sku"],
                                payload.get("external_product_id"),
                                None,
                                "published",
                                draft_variant.get("price"),
                                draft_variant.get("quantity", 0),
                                _to_json(payload),
                                datetime.now(),
                            ),
                        )
                    elif item_status == "failed":
                        fail_count += 1

            task_status = "completed" if fail_count == 0 else "completed_with_issues"
            cursor.execute(
                """
                UPDATE publish_task
                SET status = %s,
                    total_count = %s,
                    success_count = %s,
                    fail_count = %s,
                    finished_at = %s
                WHERE id = %s
                """,
                (task_status, total_count, success_count, fail_count, datetime.now(), task_id),
            )

    return get_publish_task(task_id)


def list_publish_tasks(limit: int = 100) -> list[dict[str, Any]]:
    parents = _fetch_all(
        "SELECT * FROM publish_task ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    return _attach_publish_items(parents)


def get_publish_task(task_id: int) -> dict[str, Any]:
    record = _fetch_one(
        "SELECT * FROM publish_task WHERE id = %s",
        (task_id,),
    )
    if record is None:
        raise ValueError(f"Publish task {task_id} was not found")
    return _attach_publish_items([record])[0]


def list_listing_live(limit: int = 100) -> list[dict[str, Any]]:
    return _fetch_all(
        "SELECT * FROM listing_live ORDER BY updated_at DESC LIMIT %s",
        (limit,),
    )


def _attach_product_variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    product_ids = [record["id"] for record in records]
    placeholders = ", ".join(["%s"] * len(product_ids))
    variants = _fetch_all(
        f"SELECT * FROM product_variant WHERE product_master_id IN ({placeholders}) ORDER BY id ASC",
        tuple(product_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {int(record["id"]): [] for record in records}
    for variant in variants:
        grouped[int(variant["product_master_id"])].append(variant)

    for record in records:
        record["variants"] = grouped[int(record["id"])]
    return records


def _attach_draft_variants(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    draft_ids = [record["id"] for record in records]
    placeholders = ", ".join(["%s"] * len(draft_ids))
    variants = _fetch_all(
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


def _attach_publish_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    task_ids = [record["id"] for record in records]
    placeholders = ", ".join(["%s"] * len(task_ids))
    items = _fetch_all(
        f"SELECT * FROM publish_task_item WHERE task_id IN ({placeholders}) ORDER BY id ASC",
        tuple(task_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {int(record["id"]): [] for record in records}
    for item in items:
        grouped[int(item["task_id"])].append(item)

    for record in records:
        record["items"] = grouped[int(record["id"])]
    return records


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


def _build_variant_key(color: str | None, size: str | None) -> str | None:
    parts = [part for part in (color, size) if part]
    if not parts:
        return None
    return " / ".join(parts)
