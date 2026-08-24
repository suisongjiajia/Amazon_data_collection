from __future__ import annotations

from db.connection import get_connection
from db.helpers import build_code
from db.ozon_workflow import create_ozon_publish_task, get_ozon_publish_task, get_product_edit, list_ozon_publish_tasks
from db.serialization import to_json
from integrations.ozon_seller.client import OzonSellerError
from services.ozon_listing_payload import publish_edit_to_ozon


def publish_edit(edit_id: int, *, shop_name: str | None = None, simulate: bool = True) -> dict:
    task = create_ozon_publish_task(edit_id, shop_name=shop_name)
    if simulate:
        _simulate_ozon_api_response(int(task["id"]))
    else:
        _publish_via_ozon_api(int(task["id"]))
    return get_ozon_publish_task(int(task["id"]))


def list_tasks(limit: int = 50) -> list[dict]:
    return list_ozon_publish_tasks(limit)


def _publish_via_ozon_api(task_id: int) -> None:
    task = get_ozon_publish_task(task_id)
    edit = get_product_edit(int(task["edit_id"]))
    items = task.get("items") or []

    try:
        response = publish_edit_to_ozon(edit)
        task_id_remote = response.get("result", {}).get("task_id")
        payload = to_json(response)
        success_count = 0
        with get_connection() as connection:
            with connection.cursor() as cursor:
                for item in items:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET status = %s,
                            submission_payload = %s,
                            response_payload = %s
                        WHERE id = %s
                        """,
                        (
                            "submitted",
                            payload,
                            payload,
                            item["id"],
                        ),
                    )
                    success_count += 1
                cursor.execute(
                    """
                    UPDATE ozon_publish_task
                    SET status = %s,
                        success_count = %s,
                        fail_count = 0,
                        finished_at = NOW()
                    WHERE id = %s
                    """,
                    ("completed", success_count, task_id),
                )
                cursor.execute(
                    "UPDATE product_edit SET status = %s WHERE id = %s",
                    ("published", task["edit_id"]),
                )
        if task_id_remote:
            return
    except OzonSellerError as exc:
        _mark_publish_failed(task_id, str(exc))
        raise


def _mark_publish_failed(task_id: int, error_message: str) -> None:
    task = get_ozon_publish_task(task_id)
    payload = to_json({"error": error_message})
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in task.get("items") or []:
                cursor.execute(
                    """
                    UPDATE ozon_publish_item
                    SET status = %s, response_payload = %s
                    WHERE id = %s
                    """,
                    ("failed", payload, item["id"]),
                )
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = %s, fail_count = total_count, finished_at = NOW(), error_message = %s
                WHERE id = %s
                """,
                ("failed", error_message, task_id),
            )


def _simulate_ozon_api_response(task_id: int) -> None:
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
    success_count = 0
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in items:
                submission_id = build_code("OZON")
                cursor.execute(
                    """
                    UPDATE ozon_publish_item
                    SET status = %s,
                        ozon_product_id = %s,
                        ozon_offer_id = %s,
                        submission_payload = %s,
                        response_payload = %s
                    WHERE id = %s
                    """,
                    (
                        "success",
                        submission_id,
                        f"offer-{item['seller_sku']}",
                        to_json({"simulate": True}),
                        to_json({"status": "created", "simulate": True}),
                        item["id"],
                    ),
                )
                success_count += 1
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = %s, success_count = %s, fail_count = 0, finished_at = NOW()
                WHERE id = %s
                """,
                ("completed", success_count, task_id),
            )
            cursor.execute(
                "UPDATE product_edit SET status = %s WHERE id = %s",
                ("published", task["edit_id"]),
            )
