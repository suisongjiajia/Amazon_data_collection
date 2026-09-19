from __future__ import annotations

import os
from typing import Any

from collector.ozon import OzonCollector
from collector.ozon.models import OzonProductInfo
from collector.ozon.url_parser import OzonUrlParser, OzonUrlType
from db.ozon_catalog import (
    create_ozon_collection_task,
    finish_collection_task,
    list_ozon_collection_tasks,
    list_ozon_product_families,
    save_ozon_products,
)


def _default_shop_top_n() -> int:
    raw = (os.getenv("SHOP_PIPELINE_TOP_N") or "50").strip()
    try:
        value = int(raw)
    except ValueError:
        return 50
    return max(1, min(value, 200))


def run_ozon_url_collection(url: str, *, max_products: int | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"url": url}
    if max_products is not None:
        params["max_products"] = max_products
    task = create_ozon_collection_task("url", params, source_url=url)

    try:
        products = OzonCollector().collect(url, max_products=max_products)
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


def run_ozon_shop_popular_collection(url: str, *, top_n: int | None = None) -> dict[str, Any]:
    """采集店铺「流行」排序下的 Top N 商品（默认 50）。"""
    limit = top_n if top_n is not None else _default_shop_top_n()
    parsed = OzonUrlParser().parse(url)
    if parsed.type is not OzonUrlType.SELLER:
        raise ValueError("请粘贴 Ozon 店铺链接（/seller/...），而不是单品链接")

    params = {
        "url": parsed.source_url,
        "sorting": "score",
        "top_n": limit,
        "seller_slug": parsed.seller_slug,
    }
    task = create_ozon_collection_task(
        "shop_popular",
        params,
        source_url=parsed.source_url,
    )

    try:
        products = OzonCollector().collect(parsed.source_url, max_products=limit)
        families = _build_ozon_families(products)
        saved = save_ozon_products(int(task["id"]), families)
        task = finish_collection_task(
            int(task["id"]),
            status="completed",
            total_count=len(saved),
            success_count=len(saved),
            fail_count=0,
        )
        return {
            "task": task,
            "families": saved,
            "seller_slug": parsed.seller_slug,
            "top_n": limit,
            "shop_url": parsed.source_url,
        }
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

    if strategy_type == "shop_popular":
        url = str(params.get("url") or source_url or "").strip()
        if not url:
            raise ValueError("原店铺采集任务没有可重试的链接")
        top_n = params.get("top_n")
        try:
            top_n_int = int(top_n) if top_n is not None else None
        except (TypeError, ValueError):
            top_n_int = None
        return run_ozon_shop_popular_collection(url, top_n=top_n_int)

    if strategy_type in {"url", "product_url"} or (source_url and not strategy_type):
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
    return [_build_one_family(product) for product in products]


def _build_one_family(product: OzonProductInfo) -> dict[str, Any]:
    details = {}
    raw = product.raw_payload or {}
    if isinstance(raw.get("details"), dict):
        details = raw["details"]
    aspect_variants = details.get("aspect_variants") if isinstance(details, dict) else None
    if not isinstance(aspect_variants, list):
        aspect_variants = []

    dimensions = list(product.variant_attributes.keys())
    variants = _expand_variants(product, aspect_variants)
    for variant in variants:
        for key in (variant.get("variant_attributes") or {}):
            if key not in dimensions:
                dimensions.append(key)

    return {
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
        "variant_dimensions": dimensions,
        "bullet_points": [],
        "raw_payload": product.to_dict(),
        "variants": variants,
    }


def _expand_variants(
    product: OzonProductInfo,
    aspect_variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """有规格选择器时展开为多变体；否则保持单变体。"""
    usable = [
        item
        for item in aspect_variants
        if isinstance(item, dict) and str(item.get("sku") or "").strip().isdigit()
    ]
    if len(usable) <= 1:
        attrs = dict(product.variant_attributes or {})
        if usable and isinstance(usable[0].get("attributes"), dict):
            attrs.update({str(k): str(v) for k, v in usable[0]["attributes"].items() if v})
        return [
            {
                "external_id": product.product_id,
                "source_url": product.source_url,
                "title": product.title,
                "price_text": product.price_text,
                "main_image_url": product.main_image_url,
                "variant_attributes": attrs,
                "raw_payload": product.to_dict(),
                "snapshot_time": product.collected_at,
            }
        ]

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in usable:
        sku = str(item.get("sku")).strip()
        if sku in seen:
            continue
        seen.add(sku)
        attrs = {str(k): str(v) for k, v in (item.get("attributes") or {}).items() if v}
        label = str(item.get("label") or " / ".join(attrs.values())).strip()
        title = product.title or ""
        if label and label not in title:
            title = f"{title} ({label})" if title else label
        price_text = product.price_text
        if item.get("price") is not None:
            price_text = f"{item['price']} ₽"
        variants.append(
            {
                "external_id": sku,
                "source_url": item.get("url") or f"https://www.ozon.ru/product/{sku}/",
                "title": title,
                "price_text": price_text,
                "main_image_url": item.get("image") or product.main_image_url,
                "variant_attributes": attrs,
                "raw_payload": {"aspect": item, "parent_sku": product.product_id},
                "snapshot_time": product.collected_at,
            }
        )

    # 确保当前 SKU 一定在列表中
    if product.product_id not in seen:
        variants.insert(
            0,
            {
                "external_id": product.product_id,
                "source_url": product.source_url,
                "title": product.title,
                "price_text": product.price_text,
                "main_image_url": product.main_image_url,
                "variant_attributes": dict(product.variant_attributes or {}),
                "raw_payload": product.to_dict(),
                "snapshot_time": product.collected_at,
            },
        )
    return variants
