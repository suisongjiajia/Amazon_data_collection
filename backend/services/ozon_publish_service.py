from __future__ import annotations

import time
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
from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError
from services.ozon_import_status import (
    aggregate_task_status,
    extract_import_task_id,
    is_ozon_product_sellable,
    map_ozon_import_raw_status,
    parse_import_info_items,
    parse_product_info_items,
    resolve_publish_item_status,
    summarize_item_errors,
)
from services.ozon_listing_payload import (
    build_import_items,
    build_stock_items,
    preview_listing,
)


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
        _simulate_submit(int(task["id"]), preview)
    else:
        _submit_via_ozon_api(int(task["id"]))
    return get_ozon_publish_task(int(task["id"]))


def list_tasks(limit: int = 50) -> list[dict]:
    return list_ozon_publish_tasks(limit)


def get_task(task_id: int) -> dict[str, Any]:
    return get_ozon_publish_task(task_id)


def reopen_edit_from_publish(edit_id: int) -> dict[str, Any]:
    """发布失败或审核通过后需修改内容时，重新打开编辑。"""
    return reopen_product_edit(edit_id)


def refresh_import_status(task_id: int) -> dict[str, Any]:
    """拉取 import/info + 商品详情，判定 待拉取/已推送/上架成功，并生成条码、推库存。"""
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
    if not items:
        raise ValueError("发布任务没有明细")

    if _is_simulate_task(items):
        return _finalize_simulate_success(task_id)

    import_task_id = task.get("ozon_import_task_id")
    if import_task_id is None:
        import_task_id = _recover_import_task_id(items)
    if import_task_id is None:
        raise ValueError("缺少 Ozon 导入任务 ID，请重新推送后再拉取状态")

    client = OzonSellerClient()
    try:
        info = client.get_import_info(int(import_task_id))
    except OzonSellerError as exc:
        _mark_publish_failed(task_id, error_code="OZON_IMPORT_INFO_ERROR", error_message=str(exc))
        raise

    ozon_items = parse_import_info_items(info)
    by_offer = {
        str(item.get("offer_id") or "").strip(): item
        for item in ozon_items
        if str(item.get("offer_id") or "").strip()
    }

    offer_ids = [str(item.get("seller_sku") or "").strip() for item in items if item.get("seller_sku")]
    product_by_offer: dict[str, dict[str, Any]] = {}
    try:
        product_payload = client.get_product_info_list(offer_ids=offer_ids)
        for product in parse_product_info_items(product_payload):
            offer = str(product.get("offer_id") or "").strip()
            if offer:
                product_by_offer[offer] = product
    except OzonSellerError:
        pass

    edit = get_product_edit(int(task["edit_id"]))
    stock_candidates: list[str] = []
    barcode_product_ids: list[str] = []

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in items:
                sku = str(item.get("seller_sku") or "").strip()
                ozon_item = by_offer.get(sku)
                if ozon_item is None:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET status = %s,
                            response_payload = %s,
                            error_code = NULL,
                            error_message = NULL
                        WHERE id = %s
                        """,
                        (
                            "awaiting_pull",
                            to_json({"import_info": info, "note": "offer 尚未出现在 import/info"}),
                            item["id"],
                        ),
                    )
                    continue

                import_raw = map_ozon_import_raw_status(str(ozon_item.get("status") or ""))
                product_info = product_by_offer.get(sku)
                product_id = ozon_item.get("product_id") or (product_info or {}).get("id")
                local_status, error_code, error_message = resolve_publish_item_status(
                    import_raw_status=import_raw,
                    import_errors=ozon_item.get("errors"),
                    product_info=product_info,
                )

                response_blob: dict[str, Any] = {
                    "import_info_item": ozon_item,
                    "import_info": info,
                    "product_info": product_info,
                }

                try:
                    pid_int = int(product_id or 0)
                except (TypeError, ValueError):
                    pid_int = 0
                if pid_int > 0 and local_status in {"pushed", "listed"}:
                    barcode_product_ids.append(str(pid_int))
                if local_status in {"pushed", "listed"} and sku:
                    stock_candidates.append(sku)

                cursor.execute(
                    """
                    UPDATE ozon_publish_item
                    SET status = %s,
                        ozon_product_id = %s,
                        ozon_offer_id = %s,
                        error_code = %s,
                        error_message = %s,
                        response_payload = %s
                    WHERE id = %s
                    """,
                    (
                        local_status,
                        str(pid_int) if pid_int > 0 else None,
                        sku,
                        error_code,
                        error_message,
                        to_json(response_blob),
                        item["id"],
                    ),
                )

    barcode_result: dict[str, Any] | None = None
    if barcode_product_ids:
        try:
            barcode_result = client.generate_barcodes(barcode_product_ids)
        except OzonSellerError as barcode_exc:
            barcode_result = {"error": str(barcode_exc)}

    stock_result: dict[str, Any] | None = None
    if stock_candidates:
        try:
            stock_result = _push_stocks_for_skus(edit, stock_candidates)
        except Exception as stock_exc:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_task
                        SET error_message = %s
                        WHERE id = %s
                        """,
                        (f"库存推送失败: {stock_exc}", task_id),
                    )

    if stock_candidates or barcode_result is not None:
        refreshed_products: dict[str, dict[str, Any]] = {}
        try:
            again = client.get_product_info_list(offer_ids=offer_ids)
            for product in parse_product_info_items(again):
                offer = str(product.get("offer_id") or "").strip()
                if offer:
                    refreshed_products[offer] = product
        except OzonSellerError:
            refreshed_products = product_by_offer

        with get_connection() as connection:
            with connection.cursor() as cursor:
                fresh = get_ozon_publish_task(task_id)
                for item in fresh.get("items") or []:
                    sku = str(item.get("seller_sku") or "").strip()
                    if str(item.get("status") or "") not in {"pushed", "listed"}:
                        continue
                    product_info = refreshed_products.get(sku) or product_by_offer.get(sku)
                    payload = item.get("response_payload")
                    if not isinstance(payload, dict):
                        payload = {}
                    merged = {
                        **payload,
                        "product_info": product_info,
                        "stocks": stock_result,
                        "barcodes": barcode_result,
                    }
                    new_status = "listed" if is_ozon_product_sellable(product_info) else "pushed"
                    error_code = None if new_status == "listed" else (item.get("error_code") or "NOT_SELLABLE_YET")
                    error_message = None
                    if new_status == "pushed":
                        error_message = item.get("error_message") or "商品已在 Ozon，但尚不可售（请确认库存/校验）"
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET status = %s,
                            error_code = %s,
                            error_message = %s,
                            response_payload = %s
                        WHERE id = %s
                        """,
                        (new_status, error_code, error_message, to_json(merged), item["id"]),
                    )

    return _recompute_task_totals(task_id)


def _push_stocks_for_skus(edit: dict[str, Any], skus: list[str]) -> dict[str, Any] | None:
    import os

    warehouse_id = None
    raw = (os.getenv("OZON_WAREHOUSE_ID") or "").strip()
    if raw.isdigit():
        warehouse_id = int(raw)
    if not warehouse_id:
        return None
    stocks = [
        row
        for row in build_stock_items(edit, warehouse_id)
        if str(row.get("offer_id") or "") in set(skus)
    ]
    if not stocks:
        return None
    client = OzonSellerClient()
    return client.update_stocks(stocks)


def _submit_via_ozon_api(task_id: int) -> None:
    task = get_ozon_publish_task(task_id)
    edit = get_product_edit(int(task["edit_id"]))
    items = task.get("items") or []

    try:
        payload_items = build_import_items(edit)
        offer_payload = {str(item.get("offer_id")): item for item in payload_items}
        variant_qty = {
            str(v.get("sku")): v.get("quantity")
            for v in (edit.get("variants") or [])
            if v.get("sku")
        }

        with get_connection() as connection:
            with connection.cursor() as cursor:
                for item in items:
                    sku = str(item["seller_sku"])
                    submission = dict(offer_payload.get(sku) or {"offer_id": sku})
                    if sku in variant_qty and variant_qty[sku] is not None:
                        submission["quantity"] = variant_qty[sku]
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET submission_payload = %s,
                            status = %s
                        WHERE id = %s
                        """,
                        (to_json(submission), "awaiting_pull", item["id"]),
                    )

        client = OzonSellerClient()
        import_result = client.import_products(payload_items)
        import_task_id = extract_import_task_id(import_result)
        if import_task_id is None:
            raise OzonSellerError(
                f"Ozon import 未返回 task_id，响应: {str(import_result)[:400]}"
            )

        response_blob = {
            "import": import_result,
            "ozon_import_task_id": import_task_id,
            "fulfillment": "rFBS",
            "phase": "awaiting_pull",
        }

        with get_connection() as connection:
            with connection.cursor() as cursor:
                for item in items:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET status = %s,
                            response_payload = %s,
                            error_code = NULL,
                            error_message = NULL
                        WHERE id = %s
                        """,
                        ("awaiting_pull", to_json(response_blob), item["id"]),
                    )
                cursor.execute(
                    """
                    UPDATE ozon_publish_task
                    SET status = %s,
                        ozon_import_task_id = %s,
                        success_count = 0,
                        fail_count = 0,
                        finished_at = NULL,
                        error_message = NULL
                    WHERE id = %s
                    """,
                    ("awaiting_pull", import_task_id, task_id),
                )
    except OzonSellerError as exc:
        _mark_publish_failed(task_id, error_code="OZON_API_ERROR", error_message=str(exc))
        raise
    except Exception as exc:
        _mark_publish_failed(task_id, error_code="PUBLISH_EXCEPTION", error_message=str(exc))
        raise


def _simulate_submit(task_id: int, preview: dict[str, Any]) -> None:
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
    offer_payload = {
        str(item.get("offer_id")): item for item in (preview.get("payload_items") or [])
    }
    stock_by_offer = {
        str(item.get("offer_id")): item.get("stock")
        for item in (preview.get("stock_items") or [])
        if item.get("offer_id")
    }
    fake_import_task_id = int(time.time()) % 1_000_000_000
    if fake_import_task_id < 1:
        fake_import_task_id = 1

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in items:
                sku = str(item["seller_sku"])
                submission = dict(offer_payload.get(sku) or {"offer_id": sku, "simulate": True})
                if sku in stock_by_offer:
                    submission["quantity"] = stock_by_offer[sku]
                cursor.execute(
                    """
                    UPDATE ozon_publish_item
                    SET status = %s,
                        submission_payload = %s,
                        response_payload = %s,
                        error_code = NULL,
                        error_message = NULL
                    WHERE id = %s
                    """,
                    (
                        "awaiting_pull",
                        to_json(submission),
                        to_json(
                            {
                                "simulate": True,
                                "phase": "awaiting_pull",
                                "ozon_import_task_id": fake_import_task_id,
                                "import": {"result": {"task_id": fake_import_task_id}},
                            }
                        ),
                        item["id"],
                    ),
                )
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = %s,
                    ozon_import_task_id = %s,
                    success_count = 0,
                    fail_count = 0,
                    finished_at = NULL,
                    error_message = NULL
                WHERE id = %s
                """,
                ("awaiting_pull", fake_import_task_id, task_id),
            )


def _is_simulate_task(items: list[dict[str, Any]]) -> bool:
    for item in items:
        payload = item.get("response_payload")
        if isinstance(payload, dict) and payload.get("simulate"):
            return True
        if isinstance(payload, str) and '"simulate": true' in payload.lower():
            return True
    return False


def _finalize_simulate_success(task_id: int) -> dict[str, Any]:
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
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
                        error_code = NULL,
                        error_message = NULL,
                        response_payload = %s
                    WHERE id = %s
                    """,
                    (
                        "listed",
                        submission_id,
                        item["seller_sku"],
                        to_json(
                            {
                                "simulate": True,
                                "phase": "listed",
                                "import_info_item": {
                                    "offer_id": item["seller_sku"],
                                    "status": "imported",
                                    "errors": [],
                                },
                                "product_info": {
                                    "offer_id": item["seller_sku"],
                                    "sku": 1,
                                    "statuses": {"is_created": True, "status": "price_sent"},
                                    "visibility_details": {"has_stock": True},
                                    "stocks": {"has_stock": True},
                                },
                            }
                        ),
                        item["id"],
                    ),
                )
    return _recompute_task_totals(task_id)


def _recover_import_task_id(items: list[dict[str, Any]]) -> int | None:
    for item in items:
        payload = item.get("response_payload")
        if isinstance(payload, str):
            continue
        if not isinstance(payload, dict):
            continue
        recovered = payload.get("ozon_import_task_id")
        if recovered is not None:
            try:
                return int(recovered)
            except (TypeError, ValueError):
                pass
        found = extract_import_task_id(payload.get("import") if isinstance(payload.get("import"), dict) else payload)
        if found is not None:
            return found
    return None


def _recompute_task_totals(task_id: int) -> dict[str, Any]:
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
    statuses = [str(item.get("status") or "") for item in items]
    success_count = sum(1 for s in statuses if s in {"listed", "success", "completed"})
    fail_count = sum(1 for s in statuses if s in {"failed", "pushed", "partial"})
    task_status = aggregate_task_status(statuses)
    finished = task_status in {"listed", "failed", "pushed", "completed", "partial"}

    detail_summary = summarize_item_errors(items)
    if task_status == "failed":
        task_error = detail_summary or "推送失败，请查看明细"
    elif task_status == "pushed":
        task_error = detail_summary or "已推送到 Ozon，但尚不可售（请检查库存/校验后再次拉取）"
    elif task_status == "listed":
        task_error = None
    elif task_status == "awaiting_pull":
        task_error = "推送已受理，请点击「拉取上架状态」确认是否可售"
    else:
        task_error = task.get("error_message")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = %s,
                    success_count = %s,
                    fail_count = %s,
                    finished_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    task_status,
                    success_count,
                    fail_count,
                    1 if finished else 0,
                    task_error,
                    task_id,
                ),
            )
            if task_status == "listed":
                cursor.execute(
                    "UPDATE product_edit SET status = %s WHERE id = %s",
                    ("published", task["edit_id"]),
                )

    return get_ozon_publish_task(task_id)


def _mark_publish_failed(
    task_id: int,
    *,
    error_message: str,
    error_code: str = "PUBLISH_FAILED",
) -> None:
    task = get_ozon_publish_task(task_id)
    payload = to_json({"error": error_message, "error_code": error_code, "phase": "failed"})
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
                SET status = %s,
                    fail_count = total_count,
                    success_count = 0,
                    finished_at = NOW(),
                    error_message = %s
                WHERE id = %s
                """,
                ("failed", f"[{error_code}] {error_message}", task_id),
            )
