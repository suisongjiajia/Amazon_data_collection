from __future__ import annotations

from datetime import datetime
from typing import Any

from db.connection import get_connection
from db.helpers import build_code
from db.serialization import fetch_all, fetch_one, to_json


def create_pipeline_job(
    *,
    shop_url: str,
    seller_slug: str | None = None,
    top_n: int = 50,
) -> dict[str, Any]:
    job_no = build_code("PIPE")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO shop_pipeline_job (
                    job_no, shop_url, seller_slug, top_n, status, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (job_no, shop_url, seller_slug, top_n, "queued", datetime.now()),
            )
            job_id = int(cursor.lastrowid)
    return get_pipeline_job(job_id)


def get_pipeline_job(job_id: int) -> dict[str, Any]:
    job = fetch_one("SELECT * FROM shop_pipeline_job WHERE id = %s", (job_id,))
    if job is None:
        raise ValueError(f"流水线任务 {job_id} 不存在")
    job["items"] = list_pipeline_items(job_id)
    return job


def list_pipeline_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT * FROM shop_pipeline_job
        ORDER BY id DESC
        LIMIT %s
        """,
        (limit,),
    )


def update_pipeline_job(
    job_id: int,
    *,
    status: str | None = None,
    total_count: int | None = None,
    success_count: int | None = None,
    fail_count: int | None = None,
    collection_task_id: int | None = None,
    error_message: str | None = None,
    finished: bool = False,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if total_count is not None:
        fields.append("total_count = %s")
        values.append(total_count)
    if success_count is not None:
        fields.append("success_count = %s")
        values.append(success_count)
    if fail_count is not None:
        fields.append("fail_count = %s")
        values.append(fail_count)
    if collection_task_id is not None:
        fields.append("collection_task_id = %s")
        values.append(collection_task_id)
    if error_message is not None:
        fields.append("error_message = %s")
        values.append(error_message)
    if finished:
        fields.append("finished_at = %s")
        values.append(datetime.now())
    if not fields:
        return get_pipeline_job(job_id)
    values.append(job_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE shop_pipeline_job SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
    return get_pipeline_job(job_id)


def create_pipeline_item(
    job_id: int,
    raw_product_family_id: int,
    *,
    sales_rank: int | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO shop_pipeline_item (
                    job_id, raw_product_family_id, sales_rank, status
                ) VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    sales_rank = VALUES(sales_rank),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (job_id, raw_product_family_id, sales_rank, "queued"),
            )
            item_id = int(cursor.lastrowid)
            if item_id == 0:
                cursor.execute(
                    """
                    SELECT id FROM shop_pipeline_item
                    WHERE job_id = %s AND raw_product_family_id = %s
                    """,
                    (job_id, raw_product_family_id),
                )
                row = cursor.fetchone()
                item_id = int(row[0])
    return get_pipeline_item(item_id)


def get_pipeline_item(item_id: int) -> dict[str, Any]:
    item = fetch_one(
        """
        SELECT i.*,
               f.title AS family_title,
               f.main_image_url AS family_main_image_url,
               f.external_id AS family_external_id,
               f.source_url AS family_source_url
        FROM shop_pipeline_item i
        LEFT JOIN raw_product_family f ON f.id = i.raw_product_family_id
        WHERE i.id = %s
        """,
        (item_id,),
    )
    if item is None:
        raise ValueError(f"流水线明细 {item_id} 不存在")
    return item


def list_pipeline_items(job_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT i.*,
               f.title AS family_title,
               f.main_image_url AS family_main_image_url,
               f.external_id AS family_external_id,
               f.source_url AS family_source_url
        FROM shop_pipeline_item i
        LEFT JOIN raw_product_family f ON f.id = i.raw_product_family_id
        WHERE i.job_id = %s
        ORDER BY COALESCE(i.sales_rank, 9999), i.id
        """,
        (job_id,),
    )


def update_pipeline_item(
    item_id: int,
    *,
    status: str | None = None,
    sourcing_task_id: int | None = None,
    selected_candidate_id: int | None = None,
    edit_id: int | None = None,
    publish_task_id: int | None = None,
    content_score: float | None = None,
    heal_attempts: int | None = None,
    error_message: str | None = None,
    clear_error: bool = False,
    stage_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if sourcing_task_id is not None:
        fields.append("sourcing_task_id = %s")
        values.append(sourcing_task_id)
    if selected_candidate_id is not None:
        fields.append("selected_candidate_id = %s")
        values.append(selected_candidate_id)
    if edit_id is not None:
        fields.append("edit_id = %s")
        values.append(edit_id)
    if publish_task_id is not None:
        fields.append("publish_task_id = %s")
        values.append(publish_task_id)
    if content_score is not None:
        fields.append("content_score = %s")
        values.append(content_score)
    if heal_attempts is not None:
        fields.append("heal_attempts = %s")
        values.append(heal_attempts)
    if clear_error:
        fields.append("error_message = NULL")
    elif error_message is not None:
        fields.append("error_message = %s")
        values.append(error_message)
    if stage_detail is not None:
        fields.append("stage_detail = %s")
        values.append(to_json(stage_detail))
    if not fields:
        return get_pipeline_item(item_id)
    values.append(item_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE shop_pipeline_item SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
    return get_pipeline_item(item_id)


def find_pipeline_item_by_edit(edit_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT i.*,
               f.title AS family_title,
               f.main_image_url AS family_main_image_url,
               f.external_id AS family_external_id
        FROM shop_pipeline_item i
        LEFT JOIN raw_product_family f ON f.id = i.raw_product_family_id
        WHERE i.edit_id = %s
        ORDER BY i.id DESC
        LIMIT 1
        """,
        (edit_id,),
    )


def recount_pipeline_job(job_id: int) -> dict[str, Any]:
    items = list_pipeline_items(job_id)
    success_statuses = {"pending_review", "approved", "publishing", "published"}
    fail_statuses = {
        "failed",
        "attr_missing",
        "image_failed",
        "sourcing_failed",
        "listing_failed",
        "pipeline_failed",
        "needs_fix",
        "publish_failed",
    }
    success_count = sum(1 for item in items if item.get("status") in success_statuses)
    fail_count = sum(1 for item in items if item.get("status") in fail_statuses)
    return update_pipeline_job(
        job_id,
        total_count=len(items),
        success_count=success_count,
        fail_count=fail_count,
    )
