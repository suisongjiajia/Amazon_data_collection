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
    families = [_build_one_family(product) for product in products]
    return drop_variants_listed_as_other_products(families)


def drop_variants_listed_as_other_products(families: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """店铺一次采回多件商品时，不要把另一件商品的货号当成这件的变体。"""
    owned = {str(item.get("external_id") or "").strip() for item in families}
    owned.discard("")
    if len(owned) <= 1:
        return families
    for family in families:
        root = str(family.get("external_id") or "").strip()
        variants = list(family.get("variants") or [])
        kept = [
            variant
            for variant in variants
            if str(variant.get("external_id") or "").strip() in {"", root}
            or str(variant.get("external_id") or "").strip() not in owned
        ]
        if kept:
            family["variants"] = kept
    return families


def repair_cross_listed_variants() -> dict[str, int]:
    """把已经写进库、但其实是另一件商品的变体拆出去，并把汉字颜色改成标题里的俄语颜色。"""
    import json

    from db.connection import get_connection
    from db.serialization import to_json
    from services.ozon_attribute_fill import contains_cjk, listing_color_label

    removed_raw = 0
    removed_edit = 0
    recolored = 0
    with get_connection(dict_cursor=True) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT id, external_id FROM raw_product_family")
        owners: dict[str, set[int]] = {}
        for row in cursor.fetchall():
            external_id = str(row.get("external_id") or "").strip()
            if external_id:
                owners.setdefault(external_id, set()).add(int(row["id"]))
        cursor.execute("SELECT id, family_id, external_id FROM raw_product_variant")
        drop_raw_ids: list[int] = []
        for row in cursor.fetchall():
            external_id = str(row.get("external_id") or "").strip()
            owner_ids = owners.get(external_id) or set()
            if owner_ids and int(row["family_id"]) not in owner_ids:
                drop_raw_ids.append(int(row["id"]))
        drop_raw_set = set(drop_raw_ids)

        cursor.execute(
            """
            SELECT v.id, v.sku, v.title, v.variant_attributes, v.raw_product_variant_id,
                   e.raw_product_family_id
            FROM product_edit_variant v
            JOIN product_edit e ON e.id = v.edit_id
            """
        )
        edit_rows = cursor.fetchall()
        drop_edit_ids: list[int] = []
        for row in edit_rows:
            sku = str(row.get("sku") or "")
            external_id = sku[5:] if sku.upper().startswith("OZON-") else sku
            owner_ids = owners.get(external_id) or set()
            family_id = int(row["raw_product_family_id"])
            raw_id = row.get("raw_product_variant_id")
            if (owner_ids and family_id not in owner_ids) or (
                raw_id is not None and int(raw_id) in drop_raw_set
            ):
                drop_edit_ids.append(int(row["id"]))
        if drop_edit_ids:
            placeholders = ", ".join(["%s"] * len(drop_edit_ids))
            cursor.execute(
                f"DELETE FROM ozon_publish_item WHERE edit_variant_id IN ({placeholders})",
                tuple(drop_edit_ids),
            )
            cursor.execute(
                f"DELETE FROM product_edit_variant WHERE id IN ({placeholders})",
                tuple(drop_edit_ids),
            )
            removed_edit = cursor.rowcount
        if drop_raw_ids:
            placeholders = ", ".join(["%s"] * len(drop_raw_ids))
            cursor.execute("SHOW TABLES")
            table_names = {str(next(iter(row.values()))) for row in cursor.fetchall()}
            if "selection_variant_scope" in table_names:
                cursor.execute(
                    f"DELETE FROM selection_variant_scope WHERE raw_product_variant_id IN ({placeholders})",
                    tuple(drop_raw_ids),
                )
            if "product_variant" in table_names:
                cursor.execute(
                    f"UPDATE product_variant SET raw_product_variant_id = NULL WHERE raw_product_variant_id IN ({placeholders})",
                    tuple(drop_raw_ids),
                )
            cursor.execute(
                f"DELETE FROM raw_product_variant WHERE id IN ({placeholders})",
                tuple(drop_raw_ids),
            )
            removed_raw = cursor.rowcount

        drop_edit_set = set(drop_edit_ids)
        for row in edit_rows:
            if int(row["id"]) in drop_edit_set:
                continue
            attrs = row.get("variant_attributes") or {}
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            if not isinstance(attrs, dict):
                continue
            color = str(attrs.get("Цвет") or attrs.get("Цвет товара") or "")
            if not contains_cjk(color):
                continue
            fixed = listing_color_label(color, row.get("title"))
            if not fixed:
                for key in ("Цвет", "Цвет товара", "Название цвета"):
                    attrs.pop(key, None)
            else:
                attrs["Цвет"] = fixed
                attrs["Цвет товара"] = fixed
                attrs["Название цвета"] = fixed
            cursor.execute(
                "UPDATE product_edit_variant SET variant_attributes = %s WHERE id = %s",
                (to_json(attrs), row["id"]),
            )
            recolored += 1
    return {"removed_raw": removed_raw, "removed_edit": removed_edit, "recolored": recolored}


def _build_one_family(product: OzonProductInfo) -> dict[str, Any]:
    details = {}
    raw = product.raw_payload or {}
    if isinstance(raw.get("details"), dict):
        details = raw["details"]
    aspect_variants = details.get("aspect_variants") if isinstance(details, dict) else None
    if not isinstance(aspect_variants, list):
        aspect_variants = []

    aspect_names = details.get("aspect_names") if isinstance(details, dict) else None
    if not isinstance(aspect_names, list):
        aspect_names = []
    dimensions = [str(name) for name in aspect_names if str(name).strip()]
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
    """有规格选择器时展开为多变体；支持颜色/尺码等多种区分项同时存在。"""
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

    # 只保留规格选择器上的区分属性，避免把材质/品牌等整页属性塞进每个变体
    aspect_keys: list[str] = []
    for item in usable:
        for key in (item.get("attributes") or {}):
            text = str(key).strip()
            if text and text not in aspect_keys:
                aspect_keys.append(text)

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in usable:
        sku = str(item.get("sku")).strip()
        if sku in seen:
            continue
        seen.add(sku)
        raw_attrs = {
            str(k): str(v)
            for k, v in (item.get("attributes") or {}).items()
            if str(k).strip() and str(v).strip()
        }
        attrs = {key: raw_attrs[key] for key in aspect_keys if key in raw_attrs}
        label = str(item.get("label") or " / ".join(attrs.values())).strip()
        title = product.title or ""
        if label and label not in title:
            title = f"{title} ({label})" if title else label
        price_text = None
        if sku == str(product.product_id):
            # 当前货号用详情页普通售价，不用规格按钮上可能过期的价
            price_text = product.price_text
            if not price_text and item.get("price") is not None:
                price_text = f"{item['price']} ₽"
        elif item.get("price") is not None:
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
        current_attrs = {
            key: str((product.variant_attributes or {}).get(key))
            for key in aspect_keys
            if (product.variant_attributes or {}).get(key)
        }
        variants.insert(
            0,
            {
                "external_id": product.product_id,
                "source_url": product.source_url,
                "title": product.title,
                "price_text": product.price_text,
                "main_image_url": product.main_image_url,
                "variant_attributes": current_attrs or dict(product.variant_attributes or {}),
                "raw_payload": product.to_dict(),
                "snapshot_time": product.collected_at,
            },
        )
    # 列表展示的是第一条，当前货号必须排在前面
    root_id = str(product.product_id)
    variants.sort(key=lambda item: 0 if str(item.get("external_id") or "") == root_id else 1)
    return variants
