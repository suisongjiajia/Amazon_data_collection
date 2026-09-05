# 增量迁移（新库已由 schema.py 建表，此处仅兼容旧库升级）
from __future__ import annotations

from db.connection import get_connection

MIGRATION_STATEMENTS: list[tuple[str, str, str]] = [
    (
        "raw_product_family",
        "type_id",
        """
        ALTER TABLE raw_product_family
        ADD COLUMN type_id VARCHAR(64) NULL COMMENT 'Ozon type_id' AFTER category_id
        """,
    ),
    (
        "product_edit",
        "listing_payload",
        """
        ALTER TABLE product_edit
        ADD COLUMN listing_payload JSON NULL COMMENT '已生成的上架 Listing 快照' AFTER attributes
        """,
    ),
    (
        "product_edit",
        "listing_built_at",
        """
        ALTER TABLE product_edit
        ADD COLUMN listing_built_at DATETIME NULL COMMENT 'Listing 生成时间' AFTER listing_payload
        """,
    ),
    (
        "ozon_publish_task",
        "ozon_import_task_id",
        """
        ALTER TABLE ozon_publish_task
        ADD COLUMN ozon_import_task_id BIGINT NULL COMMENT 'Ozon product/import 异步任务 ID' AFTER fail_count
        """,
    ),
]


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def run_migrations() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for table, column, statement in MIGRATION_STATEMENTS:
                if not _column_exists(cursor, table, column):
                    cursor.execute(statement)
