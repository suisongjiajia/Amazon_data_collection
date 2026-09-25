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


def sync_pipeline_item_for_edit(
    edit_id: int,
    *,
    publish_status: str,
    publish_task_id: int | None = None,
    error_message: str | None = None,
) -> None:
    """发布任务状态变化时，立刻回写流水线，避免一直停在待审核。"""
    item = find_pipeline_item_by_edit(edit_id)
    if item is None:
        return
    current = str(item.get("status") or "")
    if current in {"queued", "collecting", "sourcing", "editing", "listing", "processing"}:
        return
    status = str(publish_status or "")
    if status in {"listed", "completed", "success"}:
        update_pipeline_item(
            int(item["id"]),
            status="published",
            publish_task_id=publish_task_id,
            clear_error=True,
        )
        recount_pipeline_job(int(item["job_id"]))
        return
    if status == "failed" and current != "published":
        update_pipeline_item(
            int(item["id"]),
            status="publish_failed",
            publish_task_id=publish_task_id,
            error_message=error_message or "发布失败",
        )
        recount_pipeline_job(int(item["job_id"]))


def sync_pipeline_items_for_review(edit_id: int, *, result: str, note: str | None = None) -> int:
    """审核通过/驳回后，把关联流水线明细状态一并改掉（同一 edit 可能有多条历史明细）。"""
    rows = fetch_all(
        """
        SELECT id, job_id, status
        FROM shop_pipeline_item
        WHERE edit_id = %s
        """,
        (edit_id,),
    )
    if not rows:
        return 0
    target = "approved" if result == "approved" else "rejected"
    touched_jobs: set[int] = set()
    changed = 0
    for row in rows:
        current = str(row.get("status") or "")
        if current in {"published", "publishing"}:
            continue
        if current == target:
            continue
        update_pipeline_item(
            int(row["id"]),
            status=target,
            error_message=(note[:500] if note and target == "rejected" else None),
            clear_error=(target == "approved"),
        )
        touched_jobs.add(int(row["job_id"]))
        changed += 1
    for job_id in touched_jobs:
        recount_pipeline_job(job_id)
    return changed


def reconcile_pipeline_jobs() -> int:
    """把已经上架成功、但流水线仍显示待审核/失败的明细纠正过来；并同步已驳回的编辑。"""
    with get_connection(dict_cursor=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE shop_pipeline_item i
                JOIN product_edit pe ON pe.id = i.edit_id
                SET i.status = 'published',
                    i.error_message = NULL
                WHERE i.status NOT IN (
                    'published', 'queued', 'collecting', 'sourcing',
                    'editing', 'listing', 'processing'
                )
                  AND (
                    pe.status = 'published'
                    OR EXISTS (
                        SELECT 1 FROM ozon_publish_task t
                        WHERE t.edit_id = i.edit_id
                          AND t.status IN ('listed', 'completed')
                    )
                  )
                """
            )
            changed = int(cursor.rowcount or 0)
            cursor.execute(
                """
                UPDATE shop_pipeline_item i
                JOIN product_edit pe ON pe.id = i.edit_id
                SET i.status = 'rejected'
                WHERE pe.status = 'rejected'
                  AND i.status NOT IN (
                    'published', 'publishing', 'rejected',
                    'queued', 'collecting', 'sourcing', 'editing', 'listing', 'processing'
                  )
                """
            )
            changed += int(cursor.rowcount or 0)
            cursor.execute(
                """
                UPDATE shop_pipeline_item i
                JOIN product_edit pe ON pe.id = i.edit_id
                SET i.status = 'approved'
                WHERE pe.status = 'approved'
                  AND i.status IN ('pending_review', 'needs_fix', 'listing_failed')
                """
            )
            changed += int(cursor.rowcount or 0)
            cursor.execute("SELECT DISTINCT job_id FROM shop_pipeline_item")
            job_ids = [int(row["job_id"]) for row in cursor.fetchall()]
    for job_id in job_ids:
        recount_pipeline_job(job_id)
    return changed


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


def delete_pipeline_item(item_id: int) -> dict[str, Any]:
    """从流水线任务中移除一条明细。未发布的草稿一并删掉，避免还留在审核中心。"""
    item = get_pipeline_item(item_id)
    job_id = int(item["job_id"])
    edit_id = item.get("edit_id")
    with get_connection(dict_cursor=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM shop_pipeline_item WHERE id = %s", (item_id,))
            if edit_id:
                cursor.execute(
                    "SELECT COUNT(*) AS n FROM ozon_publish_task WHERE edit_id = %s",
                    (int(edit_id),),
                )
                published = int((cursor.fetchone() or {}).get("n") or 0)
                cursor.execute(
                    "SELECT status FROM product_edit WHERE id = %s",
                    (int(edit_id),),
                )
                edit_row = cursor.fetchone() or {}
                status = str(edit_row.get("status") or "")
                if published == 0 and status in {
                    "draft",
                    "editing",
                    "listing_ready",
                    "pending_review",
                    "needs_fix",
                    "rejected",
                }:
                    cursor.execute("DELETE FROM review_record WHERE edit_id = %s", (int(edit_id),))
                    cursor.execute("DELETE FROM product_edit WHERE id = %s", (int(edit_id),))
    job = recount_pipeline_job(job_id)
    return {"id": item_id, "deleted": True, "job": job}


def recount_pipeline_job(job_id: int) -> dict[str, Any]:
    items = list_pipeline_items(job_id)
    success_statuses = {"approved", "publishing", "published"}
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
