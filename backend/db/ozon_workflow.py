from __future__ import annotations

from datetime import datetime
from typing import Any

from db.connection import get_connection
from db.helpers import build_code
from db.serialization import fetch_all, fetch_one, to_json


def _attach_edit_variants(edit: dict[str, Any]) -> dict[str, Any]:
    edit["variants"] = fetch_all(
        "SELECT * FROM product_edit_variant WHERE edit_id = %s ORDER BY id",
        (edit["id"],),
    )
    return edit


def create_sourcing_task(raw_product_family_id: int, image_url: str) -> dict[str, Any]:
    task_no = build_code("SRC")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sourcing_task (
                    task_no, raw_product_family_id, image_url, status, started_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (task_no, raw_product_family_id, image_url, "running", datetime.now()),
            )
            task_id = cursor.lastrowid
    return get_sourcing_task(task_id)


def finish_sourcing_task(
    task_id: int,
    *,
    status: str,
    candidate_count: int,
    error_message: str | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE sourcing_task
                SET status = %s,
                    candidate_count = %s,
                    error_message = %s,
                    finished_at = %s
                WHERE id = %s
                """,
                (status, candidate_count, error_message, datetime.now(), task_id),
            )
    return get_sourcing_task(task_id)


def get_sourcing_task(task_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM sourcing_task WHERE id = %s", (task_id,))
    if record is None:
        raise ValueError(f"Sourcing task {task_id} was not found")
    return record


def list_sourcing_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT * FROM sourcing_task ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def save_supplier_candidates(
    raw_product_family_id: int,
    candidates: list[dict[str, Any]],
    *,
    sourcing_task_id: int | None = None,
) -> list[dict[str, Any]]:
    candidate_ids: list[int] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for candidate in candidates:
                cursor.execute(
                    """
                    INSERT INTO supplier_candidate (
                        sourcing_task_id,
                        raw_product_family_id,
                        supplier_name,
                        shop_name,
                        product_title,
                        product_url,
                        image_url,
                        price_text,
                        min_order_qty,
                        match_score,
                        status,
                        raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sourcing_task_id,
                        raw_product_family_id,
                        candidate.get("supplier_name"),
                        candidate.get("shop_name"),
                        candidate.get("product_title"),
                        candidate.get("product_url"),
                        candidate.get("image_url"),
                        candidate.get("price_text"),
                        candidate.get("min_order_qty"),
                        candidate.get("match_score"),
                        candidate.get("status", "candidate"),
                        to_json(candidate.get("raw_payload") or {}),
                    ),
                )
                candidate_ids.append(int(cursor.lastrowid))

    return [get_supplier_candidate(candidate_id) for candidate_id in candidate_ids]


def get_supplier_candidate(candidate_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM supplier_candidate WHERE id = %s", (candidate_id,))
    if record is None:
        raise ValueError(f"Supplier candidate {candidate_id} was not found")
    return record


def list_supplier_candidates(
    raw_product_family_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if raw_product_family_id is not None:
        return fetch_all(
            """
            SELECT * FROM supplier_candidate
            WHERE raw_product_family_id = %s
            ORDER BY match_score DESC, created_at DESC
            LIMIT %s
            """,
            (raw_product_family_id, limit),
        )
    return fetch_all(
        "SELECT * FROM supplier_candidate ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def update_supplier_candidate_status(candidate_id: int, status: str) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE supplier_candidate SET status = %s WHERE id = %s",
                (status, candidate_id),
            )
    return get_supplier_candidate(candidate_id)


def create_product_edit(raw_product_family_id: int) -> dict[str, Any]:
    from db.ozon_catalog import get_ozon_product_family

    family = get_ozon_product_family(raw_product_family_id)
    images = [family.get("main_image_url")] if family.get("main_image_url") else []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO product_edit (
                    raw_product_family_id,
                    title,
                    description,
                    bullet_points,
                    images,
                    status,
                    target_platform
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    raw_product_family_id,
                    family.get("title") or "未命名商品",
                    "",
                    to_json(family.get("bullet_points") or []),
                    to_json(images),
                    "draft",
                    "ozon",
                ),
            )
            cursor.execute(
                "SELECT id FROM product_edit WHERE raw_product_family_id = %s",
                (raw_product_family_id,),
            )
            edit_id = int(cursor.fetchone()[0])

            for variant in family.get("variants") or []:
                sku = f"OZON-{variant.get('external_id') or variant['id']}"
                cursor.execute(
                    """
                    INSERT INTO product_edit_variant (
                        edit_id,
                        raw_product_variant_id,
                        sku,
                        title,
                        price,
                        quantity,
                        image_url,
                        variant_attributes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        title = COALESCE(VALUES(title), title),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        edit_id,
                        variant["id"],
                        sku,
                        variant.get("title"),
                        None,
                        0,
                        variant.get("main_image_url"),
                        to_json(variant.get("variant_attributes") or {}),
                    ),
                )

    return get_product_edit(edit_id)


def get_product_edit(edit_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM product_edit WHERE id = %s", (edit_id,))
    if record is None:
        raise ValueError(f"Product edit {edit_id} was not found")
    return _attach_edit_variants(record)


def list_product_edits(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    if status:
        edits = fetch_all(
            """
            SELECT pe.*, rf.title AS family_title, rf.main_image_url AS family_main_image_url,
                   rf.sales_rank, rf.category_name
            FROM product_edit pe
            JOIN raw_product_family rf ON rf.id = pe.raw_product_family_id
            WHERE pe.status = %s
            ORDER BY pe.updated_at DESC
            LIMIT %s
            """,
            (status, limit),
        )
    else:
        edits = fetch_all(
            """
            SELECT pe.*, rf.title AS family_title, rf.main_image_url AS family_main_image_url,
                   rf.sales_rank, rf.category_name
            FROM product_edit pe
            JOIN raw_product_family rf ON rf.id = pe.raw_product_family_id
            ORDER BY pe.updated_at DESC
            LIMIT %s
            """,
            (limit,),
        )
    return [_attach_edit_variants(edit) for edit in edits]


def update_product_edit(
    edit_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    bullet_points: list[str] | None = None,
    images: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = %s")
        values.append(title)
    if description is not None:
        fields.append("description = %s")
        values.append(description)
    if bullet_points is not None:
        fields.append("bullet_points = %s")
        values.append(to_json(bullet_points))
    if images is not None:
        fields.append("images = %s")
        values.append(to_json(images))
    if attributes is not None:
        fields.append("attributes = %s")
        values.append(to_json(attributes))
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if not fields:
        return get_product_edit(edit_id)

    values.append(edit_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE product_edit SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
    return get_product_edit(edit_id)


def update_product_edit_variant(
    variant_id: int,
    *,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
    image_url: str | None = None,
    variant_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = %s")
        values.append(title)
    if price is not None:
        fields.append("price = %s")
        values.append(price)
    if quantity is not None:
        fields.append("quantity = %s")
        values.append(quantity)
    if image_url is not None:
        fields.append("image_url = %s")
        values.append(image_url)
    if variant_attributes is not None:
        fields.append("variant_attributes = %s")
        values.append(to_json(variant_attributes))
    if not fields:
        record = fetch_one("SELECT * FROM product_edit_variant WHERE id = %s", (variant_id,))
        if record is None:
            raise ValueError(f"Product edit variant {variant_id} was not found")
        return record

    values.append(variant_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE product_edit_variant SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
    record = fetch_one("SELECT * FROM product_edit_variant WHERE id = %s", (variant_id,))
    if record is None:
        raise ValueError(f"Product edit variant {variant_id} was not found")
    return record


def submit_product_edit_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in ("draft", "editing", "rejected"):
        raise ValueError("仅草稿或已驳回的编辑可提交审核")
    return update_product_edit(edit_id, status="pending_review")


def delete_product_edit(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in ("draft", "editing", "rejected"):
        raise ValueError("待审核或已通过的编辑不能取消")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM product_edit WHERE id = %s", (edit_id,))
    return {"id": edit_id, "deleted": True}


def create_review_record(
    edit_id: int,
    *,
    result: str,
    note: str | None = None,
    reviewer: str | None = None,
    auto_reviewed: bool = False,
) -> dict[str, Any]:
    new_status = "approved" if result == "approved" else "rejected"
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_record (edit_id, result, note, reviewer, auto_reviewed)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (edit_id, result, note, reviewer, 1 if auto_reviewed else 0),
            )
            cursor.execute(
                "UPDATE product_edit SET status = %s WHERE id = %s",
                (new_status, edit_id),
            )
            review_id = cursor.lastrowid
    return get_review_record(review_id)


def get_review_record(review_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM review_record WHERE id = %s", (review_id,))
    if record is None:
        raise ValueError(f"Review record {review_id} was not found")
    return record


def list_review_records(edit_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if edit_id is not None:
        return fetch_all(
            "SELECT * FROM review_record WHERE edit_id = %s ORDER BY created_at DESC LIMIT %s",
            (edit_id, limit),
        )
    return fetch_all(
        "SELECT * FROM review_record ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def create_ozon_publish_task(edit_id: int, *, shop_name: str | None = None) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] != "approved":
        raise ValueError("仅审核通过的商品可发布")

    task_no = build_code("OZPUB")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ozon_publish_task (
                    task_no, edit_id, shop_name, status, submit_type, submitted_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (task_no, edit_id, shop_name, "running", "api", datetime.now()),
            )
            task_id = cursor.lastrowid
            variants = edit.get("variants") or []
            for variant in variants:
                cursor.execute(
                    """
                    INSERT INTO ozon_publish_item (
                        task_id, edit_variant_id, seller_sku, status
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (task_id, variant["id"], variant["sku"], "pending"),
                )

            cursor.execute(
                "UPDATE ozon_publish_task SET total_count = %s WHERE id = %s",
                (len(variants), task_id),
            )

    return get_ozon_publish_task(task_id)


def get_ozon_publish_task(task_id: int) -> dict[str, Any]:
    task = fetch_one("SELECT * FROM ozon_publish_task WHERE id = %s", (task_id,))
    if task is None:
        raise ValueError(f"Ozon publish task {task_id} was not found")
    task["items"] = fetch_all(
        "SELECT * FROM ozon_publish_item WHERE task_id = %s ORDER BY id",
        (task_id,),
    )
    return task


def list_ozon_publish_tasks(limit: int = 50) -> list[dict[str, Any]]:
    tasks = fetch_all(
        "SELECT * FROM ozon_publish_task ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    for task in tasks:
        task["items"] = fetch_all(
            "SELECT * FROM ozon_publish_item WHERE task_id = %s ORDER BY id",
            (task["id"],),
        )
    return tasks
