from __future__ import annotations

from typing import Any


# 发布状态（任务 / 明细共用语义）
# awaiting_pull 待拉取：推送已受理，需拉取后才知可否售
# pushed        已推送：已在 Ozon 有档案，但尚不可售
# listed        上架成功：可售
# failed        推送失败


def extract_import_task_id(import_result: dict[str, Any] | None) -> int | None:
    """从 /v3/product/import 响应中提取异步 task_id。"""
    if not isinstance(import_result, dict):
        return None
    candidates: list[Any] = [import_result]
    result = import_result.get("result")
    if isinstance(result, dict):
        candidates.append(result)
    elif isinstance(result, list) and result and isinstance(result[0], dict):
        candidates.append(result[0])
    for block in candidates:
        task_id = block.get("task_id")
        if task_id is None:
            continue
        try:
            return int(task_id)
        except (TypeError, ValueError):
            continue
    return None


def parse_import_info_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """规范化 /v1/product/import/info 的 items 列表。"""
    if not isinstance(payload, dict):
        return []
    result = payload.get("result")
    if isinstance(result, dict):
        items = result.get("items")
    else:
        items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def map_ozon_import_raw_status(ozon_status: str | None) -> str:
    """
    Ozon import/info item.status -> 中间态
    imported/skipped -> imported
    failed -> failed
    pending/... -> pending
    """
    status = (ozon_status or "").strip().lower()
    if status in {"imported", "skipped"}:
        return "imported"
    if status == "failed":
        return "failed"
    return "pending"


def format_ozon_item_errors(errors: Any) -> tuple[str | None, str | None]:
    """返回 (error_code, error_message)。"""
    if not isinstance(errors, list) or not errors:
        return None, None
    codes: list[str] = []
    messages: list[str] = []
    for err in errors:
        if not isinstance(err, dict):
            continue
        code = str(err.get("code") or "").strip()
        attr_name = str(err.get("attribute_name") or "").strip()
        field = str(err.get("field") or "").strip()
        description = str(err.get("description") or "").strip()
        message = str(err.get("message") or "").strip()
        parts = [p for p in (attr_name or field, description or message) if p]
        text = ": ".join(parts) if parts else (code or "")
        if code:
            codes.append(code)
        if text:
            messages.append(text)
        elif code:
            messages.append(code)
    if not messages:
        return None, None
    return (",".join(codes[:5]) if codes else "OZON_IMPORT_ERROR"), "; ".join(messages[:8])


def parse_product_info_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return [item for item in result["items"] if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def is_ozon_product_sellable(product: dict[str, Any] | None) -> bool:
    """可售：已创建 SKU，且有库存（或可见性表明有货）。"""
    if not isinstance(product, dict) or not product:
        return False
    statuses = product.get("statuses") if isinstance(product.get("statuses"), dict) else {}
    try:
        sku_n = int(product.get("sku") or 0)
    except (TypeError, ValueError):
        sku_n = 0
    created = bool(statuses.get("is_created")) or sku_n > 0
    if not created:
        return False

    status = str(statuses.get("status") or "").strip().lower()
    if status in {"failed", "disabled", "archived", "removed"}:
        return False

    visibility = product.get("visibility_details") if isinstance(product.get("visibility_details"), dict) else {}
    stocks = product.get("stocks") if isinstance(product.get("stocks"), dict) else {}
    has_stock = bool(visibility.get("has_stock") or stocks.get("has_stock"))
    stock_rows = stocks.get("stocks")
    if not has_stock and isinstance(stock_rows, list):
        for row in stock_rows:
            if not isinstance(row, dict):
                continue
            try:
                qty = int(row.get("present") or row.get("stock") or row.get("quantity") or 0)
            except (TypeError, ValueError):
                qty = 0
            if qty > 0:
                has_stock = True
                break
    return has_stock


def resolve_publish_item_status(
    *,
    import_raw_status: str,
    import_errors: Any,
    product_info: dict[str, Any] | None,
) -> tuple[str, str | None, str | None]:
    """
    返回 (local_status, error_code, error_message)
    failed / awaiting_pull / pushed / listed
    """
    error_code, error_message = format_ozon_item_errors(import_errors)
    if import_raw_status == "failed":
        return "failed", error_code or "OZON_IMPORT_FAILED", error_message or "Ozon 导入失败"
    if import_raw_status == "pending":
        return "awaiting_pull", None, None

    # imported
    if product_info and is_ozon_product_sellable(product_info):
        return "listed", None, None

    # 已导入但尚不可售（缺尺码校验、无库存、SKU 未就绪等）
    note = error_message
    if not note and product_info:
        statuses = product_info.get("statuses") if isinstance(product_info.get("statuses"), dict) else {}
        tip = str(statuses.get("status_name") or statuses.get("status_description") or statuses.get("status") or "").strip()
        if tip:
            note = f"商品已在 Ozon，但尚不可售：{tip}"
        else:
            note = "商品已在 Ozon，但尚不可售（无库存或 SKU 未就绪）"
    elif not note:
        note = "商品已导入，但尚不可售，请检查尺寸/重量/库存后再次拉取"
    return "pushed", error_code or "NOT_SELLABLE_YET", note


def summarize_item_errors(items: list[dict[str, Any]], *, limit: int = 3) -> str | None:
    """把明细失败/不可售原因汇总成任务级可读文案。"""
    known_hints = {
        "currency_differs_from_contract": "货币与店铺合同不一致，请改 OZON_CURRENCY_CODE（跨境中卖常见 CNY）后重新生成 Listing 并推送",
        "missing_dimension": "缺少完整尺寸或重量，请到商品编辑填写长宽高与重量后重新生成 Listing 并推送",
    }
    snippets: list[str] = []
    for item in items:
        status = str(item.get("status") or "").strip().lower()
        if status not in {"failed", "pushed", "partial"}:
            continue
        sku = str(item.get("seller_sku") or item.get("offer_id") or "").strip() or "?"
        msg = str(item.get("error_message") or "").strip()
        code = str(item.get("error_code") or "").strip()
        hint = known_hints.get(code)
        if hint:
            snippets.append(f"{sku}: [{code}] {hint}")
        elif msg or code:
            snippets.append(f"{sku}: {msg or code}")
        else:
            continue
        if len(snippets) >= limit:
            break
    if not snippets:
        return None
    return "；".join(snippets)


def aggregate_task_status(item_statuses: list[str]) -> str:
    """
    明细 -> 任务：
    - 含 awaiting_pull/processing/submitted -> awaiting_pull
    - 全 listed -> listed
    - 全 failed -> failed
    - 全 pushed（或 pushed+listed 混合但无失败）-> pushed（若全 listed 已在上面）
    - 有失败与其它混合 -> failed（全失败）或保持 pushed/listed 混合用 pushed
    """
    if not item_statuses:
        return "failed"
    normalized = [str(s or "").strip().lower() for s in item_statuses]
    # 兼容旧状态
    normalized = [
        {
            "submitted": "awaiting_pull",
            "running": "awaiting_pull",
            "processing": "awaiting_pull",
            "success": "listed",
            "completed": "listed",
            "partial": "pushed",
        }.get(s, s)
        for s in normalized
    ]

    if any(s == "awaiting_pull" for s in normalized):
        return "awaiting_pull"
    if all(s == "listed" for s in normalized):
        return "listed"
    if all(s == "failed" for s in normalized):
        return "failed"
    if any(s == "failed" for s in normalized) and not any(s in {"listed", "pushed"} for s in normalized):
        return "failed"
    if any(s == "pushed" for s in normalized) or any(s == "listed" for s in normalized):
        # 有已推送/上架成功混合：任务视为已推送（未全部可售）或若全 listed 上面已返回
        if any(s == "pushed" for s in normalized) or any(s == "failed" for s in normalized):
            return "pushed"
        return "listed"
    return "awaiting_pull"


# 兼容旧测试名
def map_ozon_item_status(ozon_status: str | None) -> str:
    raw = map_ozon_import_raw_status(ozon_status)
    if raw == "imported":
        return "success"
    if raw == "failed":
        return "failed"
    return "processing"
