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


def publish_edit(
    edit_id: int,
    *,
    shop_name: str | None = None,
    simulate: bool = True,
    auto_follow: bool = False,
) -> dict:
    from services.ozon_listing_payload import apply_fixed_package_attributes, force_package_metrics_enabled
    from db.ozon_workflow import update_product_edit

    edit = get_product_edit(edit_id)
    if force_package_metrics_enabled():
        attrs = apply_fixed_package_attributes(edit.get("attributes") or {})
        update_product_edit(edit_id, attributes=attrs)
    _ensure_variant_stock_qty(edit_id, edit)
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

    result = get_ozon_publish_task(int(task["id"]))
    if auto_follow and not simulate:
        from services.publish_auto_service import start_publish_follow

        start_publish_follow(int(result["id"]), edit_id)
    return result


def list_tasks(limit: int = 50) -> list[dict]:
    return list_ozon_publish_tasks(limit)


def get_task(task_id: int) -> dict[str, Any]:
    return get_ozon_publish_task(task_id)


def reopen_edit_from_publish(edit_id: int) -> dict[str, Any]:
    """发布失败或审核通过后需修改内容时，重新打开编辑。"""
    return reopen_product_edit(edit_id)


def republish_listed_edit(edit_id: int, *, auto_follow: bool = True) -> dict[str, Any]:
    """
    已上架成功的商品：重新生成 Listing（含完整图库/统一尺寸）并再次推送更新。
    不走 reopen 清档，避免只更新图片时把 description_category_id / type_id 弄丢。
    """
    from db.ozon_workflow import update_product_edit
    from services import product_edit_service
    from services.ozon_category_resolve_service import ensure_edit_category_ids
    from services.ozon_listing_payload import apply_fixed_package_attributes, force_package_metrics_enabled

    edit = get_product_edit(edit_id)
    status = str(edit.get("status") or "")
    if status not in {"published", "approved", "listing_ready", "editing", "needs_fix"}:
        raise ValueError(f"当前状态「{status}」不可更新上架，请先回编辑或审核")

    attrs = dict(edit.get("attributes") or {})
    # 从旧 Listing 快照 / 采集 family 回填类目，避免更新图片时类目变空
    attrs = _restore_category_ids(edit, attrs)
    if force_package_metrics_enabled():
        attrs = apply_fixed_package_attributes(attrs)
    update_product_edit(edit_id, attributes=attrs, status="editing")

    try:
        ensure_edit_category_ids(edit_id, force=False)
    except Exception as exc:
        # 已有类目则继续；完全没有才失败
        edit = get_product_edit(edit_id)
        attrs = dict(edit.get("attributes") or {})
        if not str(attrs.get("description_category_id") or "").strip() or not str(attrs.get("type_id") or "").strip():
            raise ValueError(
                f"缺少 description_category_id / type_id，无法更新上架：{exc}"
            ) from exc

    built = product_edit_service.build_listing(edit_id)
    if not built.get("ok") or not built.get("saved"):
        messages = "; ".join(
            issue.get("message") or ""
            for issue in (built.get("issues") or [])
            if issue.get("severity") == "error"
        )
        raise ValueError(f"重新生成 Listing 失败：{messages or built.get('build_error') or '未知'}")

    update_product_edit(edit_id, status="approved")
    task = publish_edit(edit_id, simulate=False, auto_follow=auto_follow)
    return {
        "ok": True,
        "message": "已重新生成 Listing 并推送更新（含完整图库），后台将自动拉取状态",
        "publish_task": task,
    }


def _restore_category_ids(edit: dict[str, Any], attrs: dict[str, Any]) -> dict[str, Any]:
    """优先保留 attributes，其次旧 listing 快照，再次采集 family。"""
    from db.ozon_catalog import get_ozon_product_family

    category = str(attrs.get("description_category_id") or attrs.get("category_id") or "").strip()
    type_id = str(attrs.get("type_id") or "").strip()

    listing = edit.get("listing_payload") if isinstance(edit.get("listing_payload"), dict) else {}
    summary = listing.get("summary") if isinstance(listing.get("summary"), dict) else {}
    payload_items = listing.get("payload_items") if isinstance(listing.get("payload_items"), list) else []
    first_item = payload_items[0] if payload_items and isinstance(payload_items[0], dict) else {}

    if not category:
        category = str(
            summary.get("description_category_id")
            or first_item.get("description_category_id")
            or ""
        ).strip()
    if not type_id:
        type_id = str(summary.get("type_id") or first_item.get("type_id") or "").strip()

    if (not category or not type_id) and edit.get("raw_product_family_id"):
        try:
            family = get_ozon_product_family(int(edit["raw_product_family_id"]))
            category = category or str(family.get("category_id") or "").strip()
            type_id = type_id or str(family.get("type_id") or "").strip()
        except Exception:
            pass

    if category:
        attrs["description_category_id"] = category
    if type_id:
        attrs["type_id"] = type_id
    return attrs


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
        import_task_id = _recover_import_task_id_from_edit(int(task["edit_id"]), task_id)

    # 无导入任务 ID：按 offer_id 直接查 Ozon 已有商品（已上架成功再更新卡住时）
    if import_task_id is None:
        return _refresh_status_from_existing_offers(task_id)

    client = OzonSellerClient()
    try:
        info = client.get_import_info(int(import_task_id))
    except OzonSellerError as exc:
        # import/info 失效时，仍尝试按 SKU 同步已存在商品
        try:
            return _refresh_status_from_existing_offers(task_id)
        except Exception:
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

    # import/info 全空但商品已在架：改走 SKU 同步
    if not by_offer and product_by_offer:
        return _refresh_status_from_existing_offers(task_id)

    edit = get_product_edit(int(task["edit_id"]))
    stock_candidates: list[str] = []
    barcode_product_ids: list[str] = []

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in items:
                sku = str(item.get("seller_sku") or "").strip()
                ozon_item = by_offer.get(sku)
                product_info = product_by_offer.get(sku)
                if ozon_item is None and product_info:
                    # 导入明细暂无，但商品详情已有 → 按已有商品结算
                    local_status = "listed" if is_ozon_product_sellable(product_info) else "pushed"
                    pid = product_info.get("id") or product_info.get("product_id")
                    try:
                        pid_int = int(pid or 0)
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
                            None if local_status == "listed" else "NOT_SELLABLE_YET",
                            None if local_status == "listed" else "商品已在 Ozon，但尚不可售（请确认库存/校验）",
                            to_json({"product_info": product_info, "note": "synced_by_offer"}),
                            item["id"],
                        ),
                    )
                    continue

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

    return _finalize_after_status_sync(
        task_id,
        offer_ids=offer_ids,
        product_by_offer=product_by_offer,
        stock_candidates=stock_candidates,
        barcode_product_ids=barcode_product_ids,
        edit=edit,
    )


def _refresh_status_from_existing_offers(task_id: int) -> dict[str, Any]:
    """无 import task_id 时：按 seller_sku 查 Ozon 已有商品并同步状态/库存。"""
    task = get_ozon_publish_task(task_id)
    items = task.get("items") or []
    offer_ids = [str(item.get("seller_sku") or "").strip() for item in items if item.get("seller_sku")]
    if not offer_ids:
        raise ValueError("任务没有 SKU，无法从 Ozon 同步状态")

    client = OzonSellerClient()
    product_by_offer: dict[str, dict[str, Any]] = {}
    try:
        product_payload = client.get_product_info_list(offer_ids=offer_ids)
        for product in parse_product_info_items(product_payload):
            offer = str(product.get("offer_id") or "").strip()
            if offer:
                product_by_offer[offer] = product
    except OzonSellerError as exc:
        raise ValueError(f"按 SKU 查询 Ozon 商品失败：{exc}") from exc

    if not product_by_offer:
        raise ValueError(
            "缺少 Ozon 导入任务 ID，且后台未查到这些 SKU。"
            "若商品已在 Ozon 上架成功，请点「更新上架内容」重新推送；"
            "否则请点「再次推送」"
        )

    edit = get_product_edit(int(task["edit_id"]))
    stock_candidates: list[str] = []
    barcode_product_ids: list[str] = []

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for item in items:
                sku = str(item.get("seller_sku") or "").strip()
                product_info = product_by_offer.get(sku)
                if not product_info:
                    cursor.execute(
                        """
                        UPDATE ozon_publish_item
                        SET status = %s,
                            error_code = %s,
                            error_message = %s,
                            response_payload = %s
                        WHERE id = %s
                        """,
                        (
                            "awaiting_pull",
                            "OFFER_NOT_FOUND",
                            "Ozon 暂未查到该 SKU，请稍后重试或重新推送",
                            to_json({"note": "offer_not_found_on_ozon"}),
                            item["id"],
                        ),
                    )
                    continue

                local_status = "listed" if is_ozon_product_sellable(product_info) else "pushed"
                pid = product_info.get("id") or product_info.get("product_id")
                try:
                    pid_int = int(pid or 0)
                except (TypeError, ValueError):
                    pid_int = 0
                if pid_int > 0:
                    barcode_product_ids.append(str(pid_int))
                if sku:
                    stock_candidates.append(sku)

                # 补写最小提交快照，方便详情页展示
                submission = item.get("submission_payload")
                if not isinstance(submission, dict) or not submission.get("description_category_id"):
                    try:
                        built = build_import_items(edit)
                        by_sku = {str(row.get("offer_id")): row for row in built}
                        if sku in by_sku:
                            cursor.execute(
                                """
                                UPDATE ozon_publish_item
                                SET submission_payload = %s
                                WHERE id = %s
                                """,
                                (to_json(by_sku[sku]), item["id"]),
                            )
                    except Exception:
                        pass

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
                        None if local_status == "listed" else "NOT_SELLABLE_YET",
                        None if local_status == "listed" else "商品已在 Ozon，但尚不可售（请确认库存/校验）",
                        to_json(
                            {
                                "product_info": product_info,
                                "note": "synced_by_offer_without_import_task",
                            }
                        ),
                        item["id"],
                    ),
                )

    return _finalize_after_status_sync(
        task_id,
        offer_ids=offer_ids,
        product_by_offer=product_by_offer,
        stock_candidates=stock_candidates,
        barcode_product_ids=barcode_product_ids,
        edit=edit,
    )


def _finalize_after_status_sync(
    task_id: int,
    *,
    offer_ids: list[str],
    product_by_offer: dict[str, dict[str, Any]],
    stock_candidates: list[str],
    barcode_product_ids: list[str],
    edit: dict[str, Any],
) -> dict[str, Any]:
    client = OzonSellerClient()
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
        for attempt in range(3):
            if attempt > 0:
                time.sleep(3)
            try:
                again = client.get_product_info_list(offer_ids=offer_ids)
                for product in parse_product_info_items(again):
                    offer = str(product.get("offer_id") or "").strip()
                    if offer:
                        refreshed_products[offer] = product
            except OzonSellerError:
                if not refreshed_products:
                    refreshed_products = product_by_offer
            if stock_candidates and all(
                is_ozon_product_sellable(refreshed_products.get(sku) or product_by_offer.get(sku))
                for sku in stock_candidates
            ):
                break
            if stock_candidates and attempt < 2:
                try:
                    stock_result = _push_stocks_for_skus(edit, stock_candidates)
                except Exception:
                    pass

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


def _recover_import_task_id_from_edit(edit_id: int, current_task_id: int) -> int | None:
    """同编辑的历史发布任务里找回 import task id。"""
    from db.serialization import fetch_all

    rows = fetch_all(
        """
        SELECT id, ozon_import_task_id
        FROM ozon_publish_task
        WHERE edit_id = %s
          AND id <> %s
          AND ozon_import_task_id IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 5
        """,
        (edit_id, current_task_id),
    )
    for row in rows or []:
        try:
            return int(row["ozon_import_task_id"])
        except (TypeError, ValueError, KeyError):
            continue
    return None


def _push_stocks_for_skus(edit: dict[str, Any], skus: list[str]) -> dict[str, Any] | None:
    import os

    raw = (os.getenv("OZON_WAREHOUSE_ID") or "").strip()
    warehouse_id = None
    if raw.isdigit():
        warehouse_id = int(raw)
    if not warehouse_id:
        raise RuntimeError("未配置 OZON_WAREHOUSE_ID，无法推送 rFBS 库存")

    sku_set = set(skus)
    stocks = [
        row
        for row in build_stock_items(edit, warehouse_id)
        if str(row.get("offer_id") or "") in sku_set
    ]
    if not stocks:
        raise RuntimeError("没有可推送的库存行（变体缺少 SKU）")

    client = OzonSellerClient()
    result = client.update_stocks(stocks)
    _assert_stock_update_ok(result, expected_skus=list(sku_set))
    return result


def _assert_stock_update_ok(result: dict[str, Any] | None, *, expected_skus: list[str]) -> None:
    if not isinstance(result, dict):
        raise RuntimeError("库存接口返回为空")
    rows = result.get("result")
    if not isinstance(rows, list):
        rows = result.get("items") if isinstance(result.get("items"), list) else []
    errors: list[str] = []
    updated_offers: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        offer = str(row.get("offer_id") or "").strip()
        if offer:
            updated_offers.add(offer)
        row_errors = row.get("errors") or []
        if isinstance(row_errors, list) and row_errors:
            messages = []
            for err in row_errors:
                if isinstance(err, dict):
                    messages.append(str(err.get("message") or err.get("code") or err))
                else:
                    messages.append(str(err))
            errors.append(f"{offer or '?'}: {'; '.join(messages)}")
        elif row.get("updated") is False:
            errors.append(f"{offer or '?'}: updated=false")
    if errors:
        raise RuntimeError("库存推送部分失败: " + "; ".join(errors[:5]))
    missing = [sku for sku in expected_skus if sku and sku not in updated_offers]
    # 有些响应不回 offer_id，缺回执时不硬失败
    if missing and updated_offers:
        raise RuntimeError(f"库存未覆盖 SKU: {', '.join(missing[:5])}")


def _ensure_variant_stock_qty(edit_id: int, edit: dict[str, Any]) -> None:
    """发布前把空/0 库存回落到默认上架库存，避免 Ozon 显示库存不足。"""
    import os

    from db.ozon_workflow import update_product_edit_variant
    from services.ozon_pricing_service import DEFAULT_STOCK_QTY

    try:
        default_qty = int((os.getenv("OZON_DEFAULT_STOCK_QTY") or str(DEFAULT_STOCK_QTY)).strip())
    except ValueError:
        default_qty = DEFAULT_STOCK_QTY
    if default_qty < 1:
        default_qty = DEFAULT_STOCK_QTY

    for variant in edit.get("variants") or []:
        try:
            qty = int(variant.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty < 1 and variant.get("id"):
            update_product_edit_variant(int(variant["id"]), quantity=default_qty)


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
    fail_count = sum(1 for s in statuses if s == "failed")
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
