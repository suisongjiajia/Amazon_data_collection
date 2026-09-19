from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from db.ozon_workflow import get_product_edit, update_product_edit
from db.shop_pipeline import (
    create_pipeline_item,
    create_pipeline_job,
    get_pipeline_item,
    get_pipeline_job,
    list_pipeline_jobs,
    recount_pipeline_job,
    update_pipeline_item,
    update_pipeline_job,
)
from services import (
    ai_product_edit_service,
    ozon_collection_service,
    product_edit_service,
    sourcing_service,
)
from services.product_edit_service import apply_ai_suggestion_to_edit

logger = logging.getLogger(__name__)

_running_jobs: set[int] = set()
_lock = threading.Lock()

# 流水线明细失败分类（前端展示用，不是推送失败）
FAILURE_ATTR_MISSING = "attr_missing"
FAILURE_IMAGE = "image_failed"
FAILURE_SOURCING = "sourcing_failed"
FAILURE_LISTING = "listing_failed"
FAILURE_GENERIC = "pipeline_failed"

REVIEWABLE_FAIL_STATUSES = {
    FAILURE_ATTR_MISSING,
    FAILURE_IMAGE,
    FAILURE_SOURCING,
    FAILURE_LISTING,
    FAILURE_GENERIC,
    "needs_fix",
    "publish_failed",
    "failed",
}


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _supplier_top_n() -> int:
    return max(1, min(_env_int("SHOP_PIPELINE_SUPPLIER_TOP_N", 5), 20))


def _concurrency() -> int:
    return max(1, min(_env_int("SHOP_PIPELINE_CONCURRENCY", 4), 8))


def _auto_retry_max() -> int:
    return max(1, min(_env_int("SHOP_PIPELINE_AUTO_RETRY", 3), 5))


def _rehost_images() -> bool:
    return _env_bool("SHOP_PIPELINE_REHOST_IMAGES", False)


def classify_pipeline_error(message: str) -> str:
    text = str(message or "")
    lower = text.lower()
    if any(token in text for token in ("尺寸", "重量", "长度", "宽度", "高度", "包裹", "没有可发布的 SKU", "变体")):
        return FAILURE_ATTR_MISSING
    if any(
        token in lower
        for token in ("timeout", "timed out", "curl: (28)", "download", "下载", "connection reset", "连接")
    ):
        return FAILURE_IMAGE
    if any(token in text for token in ("1688", "货源", "搜货")):
        return FAILURE_SOURCING
    if "Listing" in text or "listing" in lower:
        return FAILURE_LISTING
    return FAILURE_GENERIC


def is_recoverable_error(message: str) -> bool:
    lower = str(message or "").lower()
    return any(
        token in lower
        for token in (
            "timeout",
            "timed out",
            "curl: (28)",
            "connection",
            "temporarily",
            "429",
            "502",
            "503",
            "504",
            "重置",
            "超时",
        )
    )


def start_shop_pipeline(shop_url: str, *, top_n: int | None = None) -> dict[str, Any]:
    """创建流水线任务并在后台跑：采集 TopN → 搜货/选供/AI/Listing → 提交审核。"""
    limit = top_n if top_n is not None else _env_int("SHOP_PIPELINE_TOP_N", 50)
    limit = max(1, min(limit, 200))

    from collector.ozon.url_parser import OzonUrlParser, OzonUrlType

    parsed = OzonUrlParser().parse(shop_url)
    if parsed.type is not OzonUrlType.SELLER:
        raise ValueError("请粘贴 Ozon 店铺链接（/seller/...）")

    job = create_pipeline_job(
        shop_url=parsed.source_url,
        seller_slug=parsed.seller_slug,
        top_n=limit,
    )
    _spawn_job(int(job["id"]))
    return get_pipeline_job(int(job["id"]))


def start_pipeline_from_collection_task(
    collection_task_id: int,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """用已完成的采集任务商品启动流水线（不再重采）。"""
    from db.ozon_catalog import get_collection_task, list_ozon_product_families_by_task

    task = get_collection_task(collection_task_id)
    if str(task.get("status") or "") != "completed":
        raise ValueError("仅「已完成」的采集任务可转入流水线")

    max_items = limit if limit is not None else _env_int("SHOP_PIPELINE_TOP_N", 50)
    max_items = max(1, min(max_items, 200))
    families = list_ozon_product_families_by_task(collection_task_id, limit=max_items)
    if not families:
        raise ValueError("该采集任务下没有可处理的商品")

    params = task.get("strategy_params") if isinstance(task.get("strategy_params"), dict) else {}
    shop_url = str(params.get("url") or task.get("source_url") or "").strip()
    if not shop_url:
        shop_url = f"collection-task:{collection_task_id}"

    seller_slug = None
    try:
        from collector.ozon.url_parser import OzonUrlParser, OzonUrlType

        parsed = OzonUrlParser().parse(shop_url)
        if parsed.type is OzonUrlType.SELLER:
            shop_url = parsed.source_url
            seller_slug = parsed.seller_slug
    except Exception:
        pass

    job = create_pipeline_job(
        shop_url=shop_url,
        seller_slug=seller_slug,
        top_n=len(families),
    )
    update_pipeline_job(
        int(job["id"]),
        status="processing",
        collection_task_id=int(task["id"]),
        total_count=len(families),
    )
    for family in families:
        create_pipeline_item(
            int(job["id"]),
            int(family["id"]),
            sales_rank=family.get("sales_rank"),
        )
    _spawn_job(int(job["id"]), process_only=True)
    return get_pipeline_job(int(job["id"]))


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return list_pipeline_jobs(limit)


def get_job(job_id: int) -> dict[str, Any]:
    return get_pipeline_job(job_id)


def retry_failed_items(job_id: int) -> dict[str, Any]:
    job = get_pipeline_job(job_id)
    failed = [
        item
        for item in (job.get("items") or [])
        if item.get("status") in REVIEWABLE_FAIL_STATUSES or item.get("status") == "failed"
    ]
    if not failed:
        return job
    for item in failed:
        update_pipeline_item(int(item["id"]), status="queued", clear_error=True)
    recount_pipeline_job(job_id)
    _spawn_job(job_id, process_only=True)
    return get_pipeline_job(job_id)


def retry_item(item_id: int) -> dict[str, Any]:
    item = get_pipeline_item(item_id)
    update_pipeline_item(item_id, status="queued", clear_error=True)
    recount_pipeline_job(int(item["job_id"]))
    _spawn_item(item_id)
    return get_pipeline_item(item_id)


def _spawn_job(job_id: int, *, process_only: bool = False) -> None:
    with _lock:
        if job_id in _running_jobs:
            return
        _running_jobs.add(job_id)

    def _runner() -> None:
        try:
            if process_only:
                _process_queued_items(job_id)
            else:
                _run_job(job_id)
        finally:
            with _lock:
                _running_jobs.discard(job_id)

    threading.Thread(target=_runner, name=f"shop-pipeline-{job_id}", daemon=True).start()


def _spawn_item(item_id: int) -> None:
    def _runner() -> None:
        try:
            _process_one_item_with_retries(item_id)
            item = get_pipeline_item(item_id)
            recount_pipeline_job(int(item["job_id"]))
        except Exception:
            logger.exception("流水线单品重试失败 item_id=%s", item_id)

    threading.Thread(target=_runner, name=f"shop-pipeline-item-{item_id}", daemon=True).start()


def _run_job(job_id: int) -> None:
    job = get_pipeline_job(job_id)
    update_pipeline_job(job_id, status="collecting")
    try:
        collected = ozon_collection_service.run_ozon_shop_popular_collection(
            job["shop_url"],
            top_n=int(job.get("top_n") or 50),
        )
        families = collected.get("families") or []
        task = collected.get("task") or {}
        update_pipeline_job(
            job_id,
            status="processing",
            collection_task_id=int(task["id"]) if task.get("id") else None,
            total_count=len(families),
        )
        for family in families:
            create_pipeline_item(
                job_id,
                int(family["id"]),
                sales_rank=family.get("sales_rank"),
            )
        _process_queued_items(job_id)
    except Exception as exc:
        logger.exception("流水线采集失败 job_id=%s", job_id)
        update_pipeline_job(
            job_id,
            status="failed",
            error_message=str(exc),
            finished=True,
        )


def _process_queued_items(job_id: int) -> None:
    update_pipeline_job(job_id, status="processing")
    job = get_pipeline_job(job_id)
    queued = [item for item in (job.get("items") or []) if item.get("status") == "queued"]
    workers = _concurrency()

    def _run(item: dict[str, Any]) -> None:
        try:
            _process_one_item_with_retries(int(item["id"]))
        except Exception as exc:
            logger.exception("流水线处理失败 item_id=%s", item.get("id"))
            _finalize_item_failure(int(item["id"]), str(exc))

    if workers <= 1 or len(queued) <= 1:
        for item in queued:
            _run(item)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"pipe-{job_id}") as pool:
            futures = [pool.submit(_run, item) for item in queued]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    logger.exception("流水线并发任务异常 job_id=%s", job_id)

    recount_pipeline_job(job_id)
    job = get_pipeline_job(job_id)
    items = job.get("items") or []
    if any(item.get("status") == "queued" for item in items):
        return
    fail_like = REVIEWABLE_FAIL_STATUSES | {"failed"}
    if all(item.get("status") in fail_like for item in items) and items:
        final_status = "failed"
    elif any(item.get("status") in fail_like for item in items):
        final_status = "partial"
    else:
        final_status = "completed"
    update_pipeline_job(job_id, status=final_status, finished=True)


def _process_one_item_with_retries(item_id: int) -> None:
    max_retries = _auto_retry_max()
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            _process_one_item(item_id, attempt=attempt)
            return
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "流水线 item_id=%s 第 %s/%s 次失败: %s",
                item_id,
                attempt,
                max_retries,
                last_error,
            )
            detail = dict(get_pipeline_item(item_id).get("stage_detail") or {})
            detail["auto_retry_count"] = attempt
            detail["last_error"] = last_error
            update_pipeline_item(item_id, stage_detail=detail, error_message=last_error)
            if attempt < max_retries:
                # 网络类稍等再试；属性类也重试（偶发类目/解析抖动），最多 3 次
                delay = min(2 * attempt, 6) if is_recoverable_error(last_error) else 1
                time.sleep(delay)
                continue
    _finalize_item_failure(item_id, last_error or "未知错误")


def _process_one_item(item_id: int, *, attempt: int = 1) -> None:
    item = get_pipeline_item(item_id)
    family_id = int(item["raw_product_family_id"])
    top_n = _supplier_top_n()
    detail: dict[str, Any] = dict(item.get("stage_detail") or {})
    detail["auto_retry_count"] = attempt

    # 1) 1688 搜货
    update_pipeline_item(item_id, status="sourcing", clear_error=True, stage_detail=detail)
    search_result = sourcing_service.search_suppliers_by_image(family_id)
    candidates = list(search_result.get("candidates") or [])
    task = search_result.get("task") or {}
    ranked = sorted(
        candidates,
        key=lambda c: float(c.get("match_score") or 0),
        reverse=True,
    )[:top_n]
    if not ranked:
        raise ValueError("1688 未返回可用货源候选")

    selected = ranked[0]
    sourcing_service.select_candidate(int(selected["id"]))
    detail["suppliers_top"] = [
        {
            "id": c.get("id"),
            "supplier_name": c.get("supplier_name"),
            "product_title": c.get("product_title"),
            "price_text": c.get("price_text"),
            "match_score": c.get("match_score"),
            "product_url": c.get("product_url"),
            "image_url": c.get("image_url"),
        }
        for c in ranked
    ]
    detail["selected_candidate_id"] = selected.get("id")
    update_pipeline_item(
        item_id,
        sourcing_task_id=int(task["id"]) if task.get("id") else None,
        selected_candidate_id=int(selected["id"]),
        stage_detail=detail,
    )

    # 2) AI 编辑（默认不转存图片，加速；可用 env 打开）
    update_pipeline_item(item_id, status="editing")
    ai_result = ai_product_edit_service.generate_product_edit(
        family_id,
        rehost_images=_rehost_images(),
    )
    edit = product_edit_service.create_edit(family_id)
    edit = apply_ai_suggestion_to_edit(int(edit["id"]), ai_result["suggestion"])
    detail["pricing"] = ai_result.get("pricing")
    detail["listing_notes"] = (ai_result.get("suggestion") or {}).get("listing_notes")
    update_pipeline_item(
        item_id,
        edit_id=int(edit["id"]),
        stage_detail=detail,
    )

    # 3) 生成 Listing 并提交审核
    update_pipeline_item(item_id, status="listing")
    built = product_edit_service.build_listing(int(edit["id"]))
    if not built.get("ok") or not built.get("saved"):
        messages = "; ".join(
            issue.get("message") or ""
            for issue in (built.get("issues") or [])
            if issue.get("severity") == "error"
        )
        raise ValueError(f"Listing 生成失败：{messages or built.get('build_error') or '校验未通过'}")

    submitted = product_edit_service.submit_for_review(int(edit["id"]))
    update_pipeline_item(
        item_id,
        status="pending_review",
        edit_id=int(submitted["id"]) if submitted.get("id") else int(edit["id"]),
        stage_detail=detail,
        clear_error=True,
    )


def _finalize_item_failure(item_id: int, error_message: str) -> None:
    """失败后尽量落到 needs_fix，便于审核中心人工修改。"""
    kind = classify_pipeline_error(error_message)
    item = get_pipeline_item(item_id)
    family_id = int(item["raw_product_family_id"])
    detail = dict(item.get("stage_detail") or {})
    detail["failure_kind"] = kind
    detail["last_error"] = error_message

    edit_id = item.get("edit_id")
    try:
        if edit_id:
            edit = get_product_edit(int(edit_id))
        else:
            edit = product_edit_service.create_edit(family_id)
            edit_id = int(edit["id"])
        attrs = dict(edit.get("attributes") or {})
        attrs["pipeline_error"] = error_message[:2000]
        attrs["failure_kind"] = kind
        update_product_edit(
            int(edit_id),
            attributes=attrs,
            status="needs_fix",
        )
    except Exception as exc:
        logger.exception("失败转待修复失败 item_id=%s: %s", item_id, exc)
        update_pipeline_item(
            item_id,
            status=kind,
            error_message=error_message,
            stage_detail=detail,
        )
        return

    update_pipeline_item(
        item_id,
        status=kind,
        edit_id=int(edit_id),
        error_message=error_message,
        stage_detail=detail,
    )
