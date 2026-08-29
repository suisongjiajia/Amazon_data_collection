from __future__ import annotations

from typing import Any

from db.connection import get_connection
from db.helpers import build_code
from db.ozon_workflow import (
    create_ozon_publish_task,
    get_ozon_publish_task,
    get_product_edit,
    list_ozon_publish_tasks,
    reopen_product_edit,
)
from db.serialization import to_json
from integrations.ozon_seller.client import OzonSellerError
from services.ozon_listing_payload import build_import_items, preview_listing, publish_edit_to_ozon


def publish_edit(edit_id: int, *, shop_name: str | None = None, simulate: bool = True) -> dict:
    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    if not preview["ok"]:
        messages = "; ".join(
            item["message"] for item in preview["issues"] if item.get("severity") == "error"
        )
        raise ValueError(f"Listing 校验未通过，无法发布：{messages or '存在错误'}")

    task = create_ozon_publish_task(edit_id, shop_name=shop_name)
    if simulate:
        _simulate_ozon_api_response(int(task["id"]), preview)
    else:
        _publish_via_ozon_api(int(task["id"]))
    return get_ozon_publish_task(int(task["id"]))


def list_tasks(limit: int = 50) -> list[dict]:
    return list_ozon_publish_tasks(limit)


def get_task(task_id: int) -> dict[str, Any]:
    return get_ozon_publish_task(task_id)


def reopen_edit_from_publish(edit_id: int) -> dict[str, Any]:
    """发布失败或审核通过后需修改内容时，重新打开编辑。"""
    return reopen_product_edit(edit_id)


def _publish_via_ozon_api(task_id: int) -> None:
    task = get_ozon_publish_task(task_id)
    edit = get_product_edit(int(task["edit_id"]))
    items = task.get("items") or []

    try:
        payload_items = build_import_items(edit)
        offer_payload = {item.get("offer_id"): item for item in payload_items}
        with get_connection() as connection:
            with connection.cursor() as cursor:
                for item in items:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET submission_payload = %s
                        WHERE id = %s
                        """,
                        (to_json(offer_payload.get(item["seller_sku"]) or {"offer_id": item["seller_sku"]}), item["id"]),
                    )

        response = publish_edit_to_ozon(edit)
        import_result = response.get("import") if isinstance(response, dict) else response
        if not isinstance(import_result, dict):
            import_result = {}
        payload = to_json(response)
        success_count = 0
        with get_connection() as connection:
            with connection.cursor() as cursor:
                for item in items:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET status = %s,
                            response_payload = %s
                        WHERE id = %s
                        """,
                        (
                            "submitted",
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
                        finished_at = NOW(),
                        error_message = NULL
                    WHERE id = %s
                    """,
                    ("completed", success_count, task_id),
                )
                cursor.execute(
                    "UPDATE product_edit SET status = %s WHERE id = %s",
                    ("published", task["edit_id"]),
                )
    except OzonSellerError as exc:
        _mark_publish_failed(task_id, error_code="OZON_API_ERROR", error_message=str(exc))
        raise
    except Exception as exc:
        _mark_publish_failed(task_id, error_code="PUBLISH_EXCEPTION", error_message=str(exc))
        raise


def _mark_publish_failed(
    task_id: int,
    *,
    error_message: str,
    error_code: str = "PUBLISH_FAILED",
) -> None:
    task = get_ozon_publish_task(task_id)
    payload = to_json({"error": error_message, "error_code": error_code})
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in task.get("items") or []:
                cursor.execute(
                    """
                    UPDATE ozon_publish_item
                    SET status = %s,
                        error_code = %s,
                        error_message = %s,
                        response_payload = %s
                    WHERE id = %s
                    """,
                    ("failed", error_code, error_message, payload, item["id"]),
                )
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = %s, fail_count = total_count, finished_at = NOW(), error_message = %s
                WHERE id = %s
                """,
                ("failed", f"[{error_code}] {error_message}", task_id),
            )


def _simulate_ozon_api_response(task_id: int, preview: dict[str, Any]) -> None:
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
    offer_payload = {
        item.get("offer_id"): item for item in (preview.get("payload_items") or [])
    }
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
                        response_payload = %s,
                        error_code = NULL,
                        error_message = NULL
                    WHERE id = %s
                    """,
                    (
                        "success",
                        submission_id,
                        f"offer-{item['seller_sku']}",
                        to_json(offer_payload.get(item["seller_sku"]) or {"simulate": True}),
                        to_json({"status": "created", "simulate": True}),
                        item["id"],
                    ),
                )
                success_count += 1
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = %s, success_count = %s, fail_count = 0, finished_at = NOW(), error_message = NULL
                WHERE id = %s
                """,
                ("completed", success_count, task_id),
            )
            cursor.execute(
                "UPDATE product_edit SET status = %s WHERE id = %s",
                ("published", task["edit_id"]),
            )
