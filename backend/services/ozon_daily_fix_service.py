"""每日扫描 Ozon 卖家后台「准备销售 / 错误 / 待修改」并自动修复。"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from db.connection import get_connection
from db.ozon_workflow import get_product_edit
from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError
from services.ozon_import_status import is_ozon_product_sellable, is_seller_paused
from services.ozon_listing_payload import build_stock_items

logger = logging.getLogger(__name__)

# 与卖家后台 Tab 大致对应的 Seller API visibility
VISIBILITY_BUCKETS: dict[str, tuple[str, ...]] = {
    "准备销售": ("READY_TO_SUPPLY", "TO_SUPPLY", "EMPTY_STOCK"),
    "错误": ("STATE_FAILED",),
    "待修改": ("VALIDATION_STATE_FAIL", "VALIDATION_STATE_PENDING"),
}

_lock = threading.Lock()
_scheduler_started = False
_last_run: dict[str, Any] | None = None
_running = False

# Windows 常无 IANA tz 数据：默认固定东八区
_FALLBACK_TZ = timezone(timedelta(hours=8), name="UTC+8")


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except ValueError:
        return default


def _tz():
    name = (os.getenv("OZON_DAILY_FIX_TZ") or "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return _FALLBACK_TZ


def find_edit_ids_by_offer_ids(offer_ids: list[str]) -> dict[str, int]:
    """offer_id(SKU) → edit_id。"""
    cleaned = [str(x).strip() for x in offer_ids if str(x).strip()]
    if not cleaned:
        return {}
    mapping: dict[str, int] = {}
    # 分批 IN 查询
    with get_connection(dict_cursor=True) as conn:
        with conn.cursor() as cur:
            for i in range(0, len(cleaned), 200):
                chunk = cleaned[i : i + 200]
                placeholders = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"""
                    SELECT sku, edit_id
                    FROM product_edit_variant
                    WHERE sku IN ({placeholders})
                    """,
                    chunk,
                )
                for row in cur.fetchall() or []:
                    sku = str(row.get("sku") or "").strip()
                    try:
                        edit_id = int(row.get("edit_id"))
                    except (TypeError, ValueError):
                        continue
                    if sku:
                        mapping[sku] = edit_id
                # 发布任务里的 offer / seller_sku 兜底
                cur.execute(
                    f"""
                    SELECT seller_sku, ozon_offer_id, pe.id AS edit_id
                    FROM ozon_publish_item pi
                    JOIN ozon_publish_task pt ON pt.id = pi.task_id
                    JOIN product_edit pe ON pe.id = pt.edit_id
                    WHERE pi.seller_sku IN ({placeholders})
                       OR pi.ozon_offer_id IN ({placeholders})
                    """,
                    chunk + chunk,
                )
                for row in cur.fetchall() or []:
                    try:
                        edit_id = int(row.get("edit_id"))
                    except (TypeError, ValueError):
                        continue
                    for key in (row.get("seller_sku"), row.get("ozon_offer_id")):
                        sku = str(key or "").strip()
                        if sku and sku not in mapping:
                            mapping[sku] = edit_id
    return mapping


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _product_error_text(product: dict[str, Any]) -> str:
    parts: list[str] = []
    errors = product.get("errors")
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, dict):
                parts.append(str(err.get("message") or err.get("code") or err))
            else:
                parts.append(str(err))
    statuses = product.get("statuses") if isinstance(product.get("statuses"), dict) else {}
    for key in ("moderate_status", "validation_status", "status_name", "status_description"):
        val = statuses.get(key)
        if val:
            parts.append(f"{key}={val}")
    return "; ".join(parts)[:1500]


def _push_stock_for_offers(offers: list[str], edit_id: int | None) -> str:
    from services import ozon_publish_service

    if not offers:
        return "skip_empty"
    warehouse_raw = (os.getenv("OZON_WAREHOUSE_ID") or "").strip()
    if not warehouse_raw.isdigit():
        raise RuntimeError("未配置 OZON_WAREHOUSE_ID")
    warehouse_id = int(warehouse_raw)
    try:
        default_qty = int((os.getenv("OZON_DEFAULT_STOCK_QTY") or "99").strip())
    except ValueError:
        default_qty = 99

    if edit_id:
        edit = get_product_edit(edit_id)
        stocks = [
            row
            for row in build_stock_items(edit, warehouse_id)
            if str(row.get("offer_id") or "") in set(offers)
        ]
        if not stocks:
            stocks = [
                {"offer_id": oid, "stock": default_qty, "warehouse_id": warehouse_id}
                for oid in offers
            ]
    else:
        stocks = [
            {"offer_id": oid, "stock": default_qty, "warehouse_id": warehouse_id}
            for oid in offers
        ]

    client = OzonSellerClient()
    result = client.update_stocks(stocks)
    ozon_publish_service._assert_stock_update_ok(result, expected_skus=offers)
    return f"stock_ok:{len(stocks)}"


def _heal_edit(edit_id: int, product: dict[str, Any]) -> str:
    from services import publish_auto_service
    from integrations.ozon_seller.client import OzonSellerClient

    # 尽量带上该 edit 全部 SKU 的 Ozon 真实拒审文案，避免本地已过校验却跳过关键修复
    edit = get_product_edit(edit_id)
    offers = [str(v.get("sku") or "") for v in (edit.get("variants") or []) if v.get("sku")]
    items = []
    messages: list[str] = []
    try:
        client = OzonSellerClient()
        for i in range(0, len(offers), 50):
            payload = client.get_product_info_list(offer_ids=offers[i : i + 50])
            products = payload.get("items") or (payload.get("result") or {}).get("items") or []
            for p in products:
                if not isinstance(p, dict):
                    continue
                offer = str(p.get("offer_id") or "").strip()
                err_text = _product_error_text(p)
                if not err_text:
                    continue
                items.append(
                    {
                        "seller_sku": offer,
                        "error_code": "OZON_DECLINE",
                        "error_message": err_text,
                    }
                )
                messages.append(f"{offer}: {err_text}")
    except Exception as exc:
        logger.warning("拉取 Ozon 报错失败 edit_id=%s: %s", edit_id, exc)

    if not messages:
        error_message = _product_error_text(product) or "daily_fix: seller visibility problem"
        items = [
            {
                "seller_sku": str(product.get("offer_id") or ""),
                "error_code": "DAILY_FIX",
                "error_message": error_message,
            }
        ]
        messages = [error_message]

    fake_task = {
        "status": "failed",
        "error_message": "; ".join(messages)[:1500],
        "items": items,
    }
    result = publish_auto_service.heal_and_republish(
        edit_id,
        source_task=fake_task,
        auto_follow=True,
        reset_attempts=True,
    )
    return str(result.get("message") or "healed")


def collect_problem_products(*, max_per_bucket: int | None = None) -> dict[str, Any]:
    """从 Ozon 拉取准备销售/错误/待修改商品。"""
    client = OzonSellerClient()
    limit = max_per_bucket if max_per_bucket is not None else _env_int("OZON_DAILY_FIX_LIMIT", 80)
    buckets: dict[str, list[dict[str, Any]]] = {}
    all_offers: list[str] = []
    all_product_ids: list[str] = []

    for label, visibilities in VISIBILITY_BUCKETS.items():
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for visibility in visibilities:
            print(f"[daily-fix] 拉取 {label}/{visibility} …", flush=True)
            try:
                listed = client.iter_product_ids(visibility=visibility, max_items=limit)
            except OzonSellerError as exc:
                logger.warning("拉取 visibility=%s 失败: %s", visibility, exc)
                print(f"[daily-fix]   拉取失败: {exc}", flush=True)
                continue
            print(f"[daily-fix]   得到 {len(listed)} 条", flush=True)
            for item in listed:
                offer = str(item.get("offer_id") or "").strip()
                pid = str(item.get("product_id") or "").strip()
                key = offer or pid
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append({"offer_id": offer, "product_id": pid, "visibility": visibility, "bucket": label})
                if offer:
                    all_offers.append(offer)
                if pid:
                    all_product_ids.append(pid)
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break
        buckets[label] = rows

    # 补全商品详情
    details_by_offer: dict[str, dict[str, Any]] = {}
    offers_unique = list(dict.fromkeys(all_offers))
    pids_unique = list(dict.fromkeys(all_product_ids))
    for chunk in _chunked(offers_unique, 50):
        if not chunk:
            continue
        try:
            payload = client.get_product_info_list(offer_ids=chunk)
        except OzonSellerError as exc:
            logger.warning("get_product_info_list(offer) 失败: %s", exc)
            continue
        items = payload.get("items") or (payload.get("result") or {}).get("items") or []
        if not isinstance(items, list):
            continue
        for product in items:
            if isinstance(product, dict):
                offer = str(product.get("offer_id") or "").strip()
                if offer:
                    details_by_offer[offer] = product
    missing_pids = [
        pid
        for pid in pids_unique
        if pid and not any(str(p.get("id") or p.get("product_id") or "") == pid for p in details_by_offer.values())
    ]
    for chunk in _chunked(missing_pids, 50):
        if not chunk:
            continue
        try:
            payload = client.get_product_info_list(product_ids=chunk)
        except OzonSellerError as exc:
            logger.warning("get_product_info_list(product_id) 失败: %s", exc)
            continue
        items = payload.get("items") or (payload.get("result") or {}).get("items") or []
        if not isinstance(items, list):
            continue
        for product in items:
            if isinstance(product, dict):
                offer = str(product.get("offer_id") or "").strip()
                if offer:
                    details_by_offer[offer] = product

    return {
        "buckets": buckets,
        "details_by_offer": details_by_offer,
        "counts": {label: len(rows) for label, rows in buckets.items()},
        "total": sum(len(rows) for rows in buckets.values()),
    }


def run_daily_fix(*, dry_run: bool = False, max_per_bucket: int | None = None) -> dict[str, Any]:
    """扫描问题商品并修复：准备销售优先补库存，错误/待修改走 AI 自愈重推。"""
    global _last_run, _running
    with _lock:
        if _running:
            # 若上次异常退出未清标志，允许超过 30 分钟后强制接手
            stale = False
            if _last_run and _last_run.get("started_at") and not _last_run.get("finished_at"):
                try:
                    started = datetime.fromisoformat(str(_last_run["started_at"]))
                    stale = (datetime.now(_tz()) - started).total_seconds() > 1800
                except Exception:
                    stale = True
            if not stale:
                return {"ok": False, "message": "已有日修任务在跑", "last_run": _last_run}
        _running = True

    started = datetime.now(_tz()).isoformat(timespec="seconds")
    summary: dict[str, Any] = {
        "ok": True,
        "started_at": started,
        "dry_run": dry_run,
        "counts": {},
        "actions": [],
        "errors": [],
        "fixed": 0,
        "skipped": 0,
        "failed": 0,
    }
    try:
        print(f"[daily-fix] 开始扫描 Ozon 问题商品…", flush=True)
        collected = collect_problem_products(max_per_bucket=max_per_bucket)
        summary["counts"] = collected["counts"]
        print(
            f"[daily-fix] 扫描完成 counts={collected['counts']} total={collected['total']}",
            flush=True,
        )
        details: dict[str, dict[str, Any]] = collected["details_by_offer"]

        # 先处理同账号 SPU 重复：归档多余卡，避免后续 AI 白烧
        try:
            from services.ozon_spu_duplicate_service import resolve_spu_duplicates

            spu_products = list(details.values())
            if spu_products and not dry_run:
                spu_result = resolve_spu_duplicates(products=spu_products, dry_run=False)
                summary["spu_archive"] = {
                    "archive_count": spu_result.get("archive_count"),
                    "archived": spu_result.get("archived"),
                    "message": spu_result.get("message"),
                }
                print(f"[daily-fix] SPU 归档: {spu_result.get('message')}", flush=True)
                archived_set = set(spu_result.get("archived") or [])
                if archived_set:
                    details = {
                        offer: product
                        for offer, product in details.items()
                        if offer not in archived_set
                    }
            elif spu_products and dry_run:
                spu_result = resolve_spu_duplicates(products=spu_products, dry_run=True)
                summary["spu_archive"] = spu_result
                print(f"[daily-fix] SPU dry-run: {spu_result.get('message')}", flush=True)
        except Exception as exc:
            logger.exception("SPU 归档阶段失败: %s", exc)
            summary["errors"].append({"stage": "spu_archive", "error": str(exc)})

        all_offers = [
            str(row.get("offer_id") or "").strip()
            for rows in collected["buckets"].values()
            for row in rows
            if row.get("offer_id")
        ]
        edit_map = find_edit_ids_by_offer_ids(all_offers)
        healed_edit_ids: set[int] = set()
        failed_edit_ids: set[int] = set()

        total_rows = sum(len(rows) for rows in collected["buckets"].values())
        done_rows = 0
        for label, rows in collected["buckets"].items():
            for row in rows:
                done_rows += 1
                offer = str(row.get("offer_id") or "").strip()
                product = details.get(offer) if offer else None
                if product is None and row.get("product_id"):
                    # 详情里可能只有 product_id 命中
                    for cand in details.values():
                        if str(cand.get("id") or cand.get("product_id") or "") == str(row.get("product_id")):
                            product = cand
                            offer = str(cand.get("offer_id") or offer).strip()
                            break
                edit_id = edit_map.get(offer)
                action = {
                    "bucket": label,
                    "visibility": row.get("visibility"),
                    "offer_id": offer,
                    "product_id": row.get("product_id"),
                    "edit_id": edit_id,
                }
                print(
                    f"[daily-fix] ({done_rows}/{total_rows}) {label} offer={offer or row.get('product_id')} edit={edit_id}",
                    flush=True,
                )
                try:
                    if product and is_seller_paused(product):
                        action["result"] = "skipped_paused"
                        summary["skipped"] += 1
                        summary["actions"].append(action)
                        continue
                    if product and is_ozon_product_sellable(product) and label == "准备销售":
                        action["result"] = "already_sellable"
                        summary["skipped"] += 1
                        summary["actions"].append(action)
                        continue

                    if dry_run:
                        action["result"] = "dry_run"
                        summary["skipped"] += 1
                        summary["actions"].append(action)
                        continue

                    if label == "准备销售":
                        # 优先补库存；仍有本地稿且带校验错误时再自愈（同一 edit 只自愈一次）
                        msg = _push_stock_for_offers([offer] if offer else [], edit_id)
                        action["result"] = msg
                        err_text = _product_error_text(product or {})
                        need_heal = bool(
                            edit_id
                            and err_text
                            and any(
                                token in err_text.lower()
                                for token in ("error", "ошиб", "неверн", "attribute", "атрибут")
                            )
                        )
                        if need_heal and edit_id in failed_edit_ids:
                            action["result"] = f"{msg}; heal_skip_failed_edit_{edit_id}"
                        elif need_heal and edit_id not in healed_edit_ids:
                            action["result"] = f"{msg}; {_heal_edit(edit_id, product or {})}"
                            healed_edit_ids.add(edit_id)
                        elif need_heal:
                            action["result"] = f"{msg}; heal_deduped_edit_{edit_id}"
                        summary["fixed"] += 1
                    else:
                        if not edit_id:
                            action["result"] = "orphan_no_local_edit"
                            summary["skipped"] += 1
                        elif edit_id in failed_edit_ids:
                            action["result"] = f"heal_skip_failed_edit_{edit_id}"
                            summary["skipped"] += 1
                        elif edit_id in healed_edit_ids:
                            action["result"] = f"heal_deduped_edit_{edit_id}"
                            summary["skipped"] += 1
                        else:
                            action["result"] = _heal_edit(edit_id, product or {})
                            healed_edit_ids.add(edit_id)
                            summary["fixed"] += 1
                    print(f"[daily-fix]   -> {action.get('result')}", flush=True)
                    summary["actions"].append(action)
                except Exception as exc:
                    if edit_id:
                        failed_edit_ids.add(edit_id)
                    logger.warning("日修失败 offer=%s edit_id=%s: %s", offer, edit_id, exc)
                    print(f"[daily-fix]   -> FAIL {exc}", flush=True)
                    action["result"] = f"error:{exc}"
                    summary["failed"] += 1
                    summary["errors"].append(f"{offer or row.get('product_id')}: {exc}")
                    summary["actions"].append(action)

        summary["finished_at"] = datetime.now(_tz()).isoformat(timespec="seconds")
        summary["message"] = (
            f"日修完成：扫描 {collected['total']}，修复 {summary['fixed']}，"
            f"跳过 {summary['skipped']}，失败 {summary['failed']}"
        )
        summary["ok"] = summary["failed"] == 0 or summary["fixed"] > 0
    except Exception as exc:
        logger.exception("日修任务异常: %s", exc)
        summary["ok"] = False
        summary["message"] = str(exc)
        summary["finished_at"] = datetime.now(_tz()).isoformat(timespec="seconds")
    finally:
        with _lock:
            _running = False
            _last_run = summary
    return summary


def get_daily_fix_status() -> dict[str, Any]:
    return {
        "enabled": _env_bool("OZON_DAILY_FIX_ENABLED", True),
        "hour": _env_int("OZON_DAILY_FIX_HOUR", 3),
        "minute": _env_int("OZON_DAILY_FIX_MINUTE", 0),
        "tz": str(_tz()),
        "limit_per_bucket": _env_int("OZON_DAILY_FIX_LIMIT", 80),
        "running": _running,
        "last_run": _last_run,
        "buckets": {k: list(v) for k, v in VISIBILITY_BUCKETS.items()},
    }


def _seconds_until_next_run() -> float:
    now = datetime.now(_tz())
    hour = max(0, min(_env_int("OZON_DAILY_FIX_HOUR", 3), 23))
    minute = max(0, min(_env_int("OZON_DAILY_FIX_MINUTE", 0), 59))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(5.0, (target - now).total_seconds())


def _scheduler_loop() -> None:
    logger.info(
        "Ozon 日修调度已启动：每天 %02d:%02d (%s)",
        _env_int("OZON_DAILY_FIX_HOUR", 3),
        _env_int("OZON_DAILY_FIX_MINUTE", 0),
        _tz(),
    )
    while True:
        if not _env_bool("OZON_DAILY_FIX_ENABLED", True):
            time.sleep(60)
            continue
        wait = _seconds_until_next_run()
        logger.info("Ozon 日修下次执行还有 %.0f 秒", wait)
        time.sleep(wait)
        if not _env_bool("OZON_DAILY_FIX_ENABLED", True):
            continue
        try:
            result = run_daily_fix()
            logger.info("Ozon 日修结果: %s", result.get("message"))
        except Exception:
            logger.exception("Ozon 日修调度执行失败")
        # 避免同一分钟内重复触发
        time.sleep(65)


def start_daily_fix_scheduler() -> None:
    global _scheduler_started
    if _scheduler_started:
        return
    if not _env_bool("OZON_DAILY_FIX_ENABLED", True):
        logger.info("OZON_DAILY_FIX_ENABLED=false，跳过日修调度")
        return
    _scheduler_started = True
    thread = threading.Thread(target=_scheduler_loop, name="ozon-daily-fix", daemon=True)
    thread.start()
