from datetime import datetime
from typing import Any

import database
from repositories.draft_repository import get_listing_draft


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
    task_no = database._build_code("PUB")
    task_shop_name = shop_name or drafts[0]["shop_name"]
    task_marketplace = marketplace or drafts[0]["marketplace"]

    with database.get_connection() as connection:
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
                    payload, issues = database._build_publish_payload(
                        draft,
                        draft_variant,
                        task_shop_name,
                        task_marketplace,
                    )
                    item_status = "success" if not issues and simulate else "failed" if issues else "pending"
                    error_code = "VALIDATION_ERROR" if issues else None
                    error_message = "; ".join(issue["message"] for issue in issues) if issues else None
                    submission_id = database._build_code("SIM") if item_status == "success" else None

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
                            database._to_json(issues),
                            database._to_json(payload),
                        ),
                    )
                    publish_item_id = cursor.lastrowid

                    if item_status == "success":
                        success_count += 1
                        live_record = database._build_live_listing_record(
                            publish_item_id,
                            draft,
                            draft_variant,
                            task_shop_name,
                            task_marketplace,
                            payload,
                        )
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
                                live_record["publish_task_item_id"],
                                live_record["draft_id"],
                                live_record["variant_id"],
                                live_record["shop_name"],
                                live_record["marketplace"],
                                live_record["seller_sku"],
                                live_record["asin"],
                                live_record["parent_asin"],
                                live_record["listing_status"],
                                live_record["price"],
                                live_record["quantity"],
                                database._to_json(live_record["live_payload"]),
                                live_record["last_sync_at"],
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
                (
                    task_status,
                    total_count,
                    success_count,
                    fail_count,
                    datetime.now(),
                    task_id,
                ),
            )

    return get_publish_task(task_id)


def list_publish_tasks(limit: int = 100) -> list[dict[str, Any]]:
    parents = database._fetch_all(
        "SELECT * FROM publish_task ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )
    return attach_publish_items(parents)


def get_publish_task(task_id: int) -> dict[str, Any]:
    record = database._fetch_one(
        "SELECT * FROM publish_task WHERE id = %s",
        (task_id,),
    )
    if record is None:
        raise ValueError(f"Publish task {task_id} was not found")
    return attach_publish_items([record])[0]


def attach_publish_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    task_ids = [record["id"] for record in records]
    placeholders = ", ".join(["%s"] * len(task_ids))
    items = database._fetch_all(
        f"SELECT * FROM publish_task_item WHERE task_id IN ({placeholders}) ORDER BY id ASC",
        tuple(task_ids),
    )

    grouped: dict[int, list[dict[str, Any]]] = {int(record["id"]): [] for record in records}
    for item in items:
        grouped[int(item["task_id"])].append(item)

    for record in records:
        record["items"] = grouped[int(record["id"])]
    return records
