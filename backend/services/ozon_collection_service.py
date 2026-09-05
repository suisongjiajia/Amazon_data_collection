from __future__ import annotations

from typing import Any

from collector.ozon import OzonCollector
from collector.ozon.models import OzonProductInfo
from db.ozon_catalog import (
    create_ozon_collection_task,
    finish_collection_task,
    list_ozon_collection_tasks,
    list_ozon_product_families,
    save_ozon_products,
)


def run_ozon_url_collection(url: str) -> dict[str, Any]:
    task = create_ozon_collection_task("url", {"url": url}, source_url=url)

    try:
        products = OzonCollector().collect(url)
        families = _build_ozon_families(products)
        saved = save_ozon_products(int(task["id"]), families)
        task = finish_collection_task(
            int(task["id"]),
            status="completed",
            total_count=len(saved),
            success_count=len(saved),
            fail_count=0,
        )
        return {"task": task, "families": saved}
    except Exception as exc:
        finish_collection_task(
            int(task["id"]),
            status="failed",
            total_count=0,
            success_count=0,
            fail_count=1,
            error_message=str(exc),
        )
        raise


def run_ozon_collection_task(
    strategy_type: str,
    strategy_params: dict[str, Any],
    *,
    source_url: str = "",
) -> dict[str, Any]:
    task = create_ozon_collection_task(strategy_type, strategy_params, source_url=source_url)

    try:
        products = OzonCollector().collect_with_strategy(strategy_type, strategy_params)
        families = _build_ozon_families(products)
        saved = save_ozon_products(int(task["id"]), families)
        task = finish_collection_task(
            int(task["id"]),
            status="completed",
            total_count=len(saved),
            success_count=len(saved),
            fail_count=0,
        )
        return {"task": task, "families": saved}
    except Exception as exc:
        finish_collection_task(
            int(task["id"]),
            status="failed",
            total_count=0,
            success_count=0,
            fail_count=1,
            error_message=str(exc),
        )
        raise


def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return list_ozon_collection_tasks(limit)


def list_families(limit: int = 100) -> list[dict[str, Any]]:
    return list_ozon_product_families(limit)


def retry_collection_task(task_id: int) -> dict[str, Any]:
    """按原任务的链接/策略重新发起一次采集（新建任务，不覆盖旧记录）。"""
    from db.ozon_catalog import get_collection_task

    task = get_collection_task(task_id)
    strategy_type = str(task.get("strategy_type") or "").strip()
    params = task.get("strategy_params") if isinstance(task.get("strategy_params"), dict) else {}
    source_url = str(task.get("source_url") or "").strip()

    if strategy_type in {"url", "product_url"} or source_url:
        url = str(params.get("url") or source_url or "").strip()
        if not url:
            raise ValueError("原任务没有可重试的采集链接")
        return run_ozon_url_collection(url)

    if not strategy_type:
        raise ValueError("原任务缺少策略类型，无法重新采集")
    return run_ozon_collection_task(
        strategy_type,
        dict(params),
        source_url=source_url,
    )


def _build_ozon_families(products: list[OzonProductInfo]) -> list[dict[str, Any]]:
    return [
        {
            "external_id": product.product_id,
            "source_url": product.source_url,
            "title": product.title,
            "brand": product.brand,
            "rating": product.rating,
            "review_count": product.review_count,
            "main_image_url": product.main_image_url,
            "sales_rank": product.sales_rank,
            "category_id": product.category_id,
            "type_id": product.type_id,
            "category_name": product.category_name,
            "hot_score": product.hot_score,
            "variant_dimensions": list(product.variant_attributes.keys()),
            "bullet_points": [],
            "raw_payload": product.to_dict(),
            "variants": [
                {
                    "external_id": product.product_id,
                    "source_url": product.source_url,
                    "title": product.title,
                    "price_text": product.price_text,
                    "main_image_url": product.main_image_url,
                    "variant_attributes": product.variant_attributes,
                    "raw_payload": product.to_dict(),
                    "snapshot_time": product.collected_at,
                }
            ],
        }
        for product in products
    ]
