from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from collector.alibaba1688.shop_collector import Alibaba1688Offer, Alibaba1688ShopCollector
from collector.alibaba1688.url_parser import Alibaba1688UrlParser, Alibaba1688UrlType
from db.connection import get_connection
from db.helpers import build_code
from db.ozon_catalog import finish_collection_task, get_collection_task
from db.serialization import fetch_all, fetch_one, to_json


def _default_top_n() -> int:
    raw = (os.getenv("1688_SHOP_TOP_N") or os.getenv("SHOP_PIPELINE_TOP_N") or "50").strip()
    try:
        value = int(raw)
    except ValueError:
        return 50
    return max(1, min(value, 200))


def create_1688_collection_task(
    strategy_type: str,
    strategy_params: dict[str, Any],
    *,
    source_url: str = "",
) -> dict[str, Any]:
    task_no = build_code("A1688")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO collection_task (
                    task_no,
                    source_type,
                    source_url,
                    marketplace,
                    platform,
                    strategy_type,
                    strategy_params,
                    status,
                    started_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_no,
                    strategy_type,
                    source_url or f"1688:{strategy_type}",
                    "1688.com",
                    "1688",
                    strategy_type,
                    to_json(strategy_params),
                    "running",
                    datetime.now(),
                ),
            )
            task_id = cursor.lastrowid
    return get_collection_task(int(task_id))


def save_1688_products(task_id: int, offers: list[Alibaba1688Offer]) -> list[dict[str, Any]]:
    family_ids: list[int] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for index, offer in enumerate(offers):
                family_key = f"1688:{offer.offer_id}"
                rank = int((offer.raw_payload or {}).get("sales_rank") or (index + 1))
                variants = _build_variants(offer)
                cursor.execute(
                    """
                    INSERT INTO raw_product_family (
                        task_id,
                        family_key,
                        marketplace,
                        platform,
                        external_id,
                        source_url,
                        title,
                        brand,
                        main_image_url,
                        sales_rank,
                        category_name,
                        variant_dimensions,
                        bullet_points,
                        raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        task_id = VALUES(task_id),
                        title = COALESCE(VALUES(title), title),
                        brand = COALESCE(VALUES(brand), brand),
                        main_image_url = COALESCE(VALUES(main_image_url), main_image_url),
                        sales_rank = COALESCE(VALUES(sales_rank), sales_rank),
                        category_name = COALESCE(VALUES(category_name), category_name),
                        raw_payload = VALUES(raw_payload),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        task_id,
                        family_key,
                        "1688.com",
                        "1688",
                        offer.offer_id,
                        offer.source_url,
                        offer.title,
                        offer.shop_name,
                        offer.main_image_url,
                        rank,
                        offer.shop_name,
                        to_json(list((offer.attributes or {}).keys())[:20]),
                        to_json(offer.images or []),
                        to_json(
                            {
                                "images": offer.images,
                                "attributes": offer.attributes,
                                "skus": offer.skus,
                                "raw": offer.raw_payload,
                                "price_text": offer.price_text,
                            }
                        ),
                    ),
                )
                cursor.execute(
                    "SELECT id FROM raw_product_family WHERE family_key = %s",
                    (family_key,),
                )
                family_row = cursor.fetchone()
                family_id = int(family_row[0])
                family_ids.append(family_id)

                kept_external_ids: list[str] = []
                for variant in variants:
                    external_id = str(variant["external_id"])
                    kept_external_ids.append(external_id)
                    cursor.execute(
                        """
                        SELECT id FROM raw_product_variant
                        WHERE family_id = %s AND external_id = %s
                        """,
                        (family_id, external_id),
                    )
                    existing = cursor.fetchone()
                    asin = f"{family_id}:{external_id}"[:32]
                    if existing:
                        cursor.execute(
                            """
                            UPDATE raw_product_variant
                            SET source_url = COALESCE(%s, source_url),
                                title = COALESCE(%s, title),
                                price_text = %s,
                                main_image_url = %s,
                                color = COALESCE(%s, color),
                                size = COALESCE(%s, size),
                                variant_attributes = %s,
                                raw_payload = %s,
                                snapshot_time = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s
                            """,
                            (
                                variant.get("source_url"),
                                variant.get("title"),
                                variant.get("price_text"),
                                variant.get("main_image_url"),
                                variant.get("color"),
                                variant.get("size"),
                                to_json(variant.get("variant_attributes") or {}),
                                to_json(variant.get("raw_payload") or {}),
                                datetime.now(),
                                existing[0],
                            ),
                        )
                    else:
                        cursor.execute(
                            """
                            INSERT INTO raw_product_variant (
                                family_id,
                                asin,
                                external_id,
                                source_url,
                                title,
                                price_text,
                                main_image_url,
                                color,
                                size,
                                variant_attributes,
                                raw_payload,
                                snapshot_time
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                family_id,
                                asin,
                                external_id,
                                variant.get("source_url"),
                                variant.get("title"),
                                variant.get("price_text"),
                                variant.get("main_image_url"),
                                variant.get("color"),
                                variant.get("size"),
                                to_json(variant.get("variant_attributes") or {}),
                                to_json(variant.get("raw_payload") or {}),
                                datetime.now(),
                            ),
                        )
                # 删除本轮未出现的旧规格（先清审核变体外键，再删 raw）
                if kept_external_ids:
                    placeholders = ", ".join(["%s"] * len(kept_external_ids))
                    cursor.execute(
                        f"""
                        SELECT id FROM raw_product_variant
                        WHERE family_id = %s AND external_id NOT IN ({placeholders})
                        """,
                        (family_id, *kept_external_ids),
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM raw_product_variant WHERE family_id = %s",
                        (family_id,),
                    )
                stale_ids = [int(row[0]) for row in cursor.fetchall()]
                if stale_ids:
                    stale_ph = ", ".join(["%s"] * len(stale_ids))
                    cursor.execute(
                        f"""
                        DELETE FROM product_edit_variant
                        WHERE raw_product_variant_id IN ({stale_ph})
                        """,
                        tuple(stale_ids),
                    )
                    cursor.execute(
                        f"""
                        DELETE FROM raw_product_variant
                        WHERE id IN ({stale_ph})
                        """,
                        tuple(stale_ids),
                    )

    return [get_1688_product_family(family_id) for family_id in family_ids]


def _build_variants(offer: Alibaba1688Offer) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    gallery = [str(u).strip() for u in (offer.images or []) if str(u).strip()]
    # 其它规格的主图，避免灰/棕等色图互串进副图
    style_images = {
        str(sku.get("image_url") or "").strip()
        for sku in (offer.skus or [])
        if str(sku.get("image_url") or "").strip()
    }
    if offer.skus:
        for index, sku in enumerate(offer.skus):
            color = str(sku.get("color") or "").strip()
            size = str(sku.get("size") or "").strip()
            label = str(sku.get("label") or "").strip()
            if not label:
                label = " / ".join(part for part in (color, size) if part) or f"规格{index + 1}"
            # Ozon 合卡通常一个区分项：双轴时合成「款式 · 尺码」
            if color and size:
                distinguish = f"{color} · {size}"
            else:
                distinguish = color or size or label
            sku_price = str(sku.get("price_text") or "").strip() or offer.price_text
            sku_image = str(sku.get("image_url") or "").strip() or offer.main_image_url
            other_style = {url for url in style_images if url and url != sku_image}
            variant_images: list[str] = []
            if sku_image:
                variant_images.append(sku_image)
            for url in gallery:
                if url in variant_images or url in other_style:
                    continue
                variant_images.append(url)
            from collector.alibaba1688.image_filter import filter_1688_product_images

            variant_images = filter_1688_product_images(
                variant_images,
                max_count=12,
                prefer=[sku_image] if sku_image else None,
            )
            variant_attrs: dict[str, Any] = {
                "规格": label,
                "区分项": distinguish,
            }
            if color:
                variant_attrs["款式"] = color
                variant_attrs["颜色"] = color
                variant_attrs["Цвет"] = distinguish if size else color
                variant_attrs["Цвет товара"] = distinguish if size else color
            if size:
                variant_attrs["尺码"] = size
                variant_attrs["Размер"] = size
                variant_attrs["Размер товара"] = size
            for key, value in sku.items():
                if key in {
                    "label",
                    "name",
                    "image_url",
                    "price_text",
                    "color",
                    "size",
                    "spec_axes",
                    "axis_props",
                }:
                    continue
                if value not in (None, ""):
                    variant_attrs[key] = value
            if sku_price:
                variant_attrs["price_text"] = sku_price
            if variant_images:
                variant_attrs["image_url"] = variant_images[0]
                variant_attrs["images"] = variant_images
            # 每 SKU 写入包装（cm→mm），供审核/运费使用
            try:
                l_cm = float(sku.get("length_cm") or 0)
                w_cm = float(sku.get("width_cm") or 0)
                h_cm = float(sku.get("height_cm") or 0)
                weight_g = int(float(sku.get("weight_g") or 0))
            except (TypeError, ValueError):
                l_cm = w_cm = h_cm = 0
                weight_g = 0
            if l_cm > 0 and w_cm > 0 and h_cm > 0 and weight_g > 0:
                depth = max(1, int(round(l_cm * 10)))
                width = max(1, int(round(w_cm * 10)))
                height = max(1, int(round(h_cm * 10)))
                variant_attrs.update(
                    {
                        "depth_mm": str(depth),
                        "width_mm": str(width),
                        "height_mm": str(height),
                        "weight_g": str(weight_g),
                        "Длина, мм": str(depth),
                        "Ширина, мм": str(width),
                        "Высота, мм": str(height),
                        "Вес, г": str(weight_g),
                        "package_manual": "1",
                    }
                )
            external = str(sku.get("sku_id") or "").strip() or f"{offer.offer_id}-{index + 1}"
            rows.append(
                {
                    "external_id": external,
                    "source_url": offer.source_url,
                    "title": f"{offer.title or offer.offer_id} / {label}",
                    "price_text": sku_price,
                    "main_image_url": (variant_images[0] if variant_images else sku_image),
                    "color": distinguish,
                    "size": size or None,
                    "variant_attributes": variant_attrs,
                    "raw_payload": sku,
                }
            )
    if not rows:
        fallback_images = list(gallery)
        if offer.main_image_url and offer.main_image_url not in fallback_images:
            fallback_images.insert(0, offer.main_image_url)
        fallback_images = fallback_images[:15]
        attrs = dict(offer.attributes or {})
        if fallback_images:
            attrs["image_url"] = fallback_images[0]
            attrs["images"] = fallback_images
        rows.append(
            {
                "external_id": offer.offer_id,
                "source_url": offer.source_url,
                "title": offer.title or offer.offer_id,
                "price_text": offer.price_text,
                "main_image_url": fallback_images[0] if fallback_images else offer.main_image_url,
                "color": None,
                "size": None,
                "variant_attributes": attrs,
                "raw_payload": {},
            }
        )
    return rows


def get_1688_product_family(family_id: int) -> dict[str, Any]:
    family = fetch_one(
        "SELECT * FROM raw_product_family WHERE id = %s AND platform = '1688'",
        (family_id,),
    )
    if family is None:
        raise ValueError(f"1688 product family {family_id} was not found")
    family["variants"] = fetch_all(
        "SELECT * FROM raw_product_variant WHERE family_id = %s ORDER BY id",
        (family_id,),
    )
    family["variant_count"] = len(family["variants"])
    return family


def run_1688_shop_collection(shop_url: str, *, top_n: int | None = None) -> dict[str, Any]:
    """采集 1688 整店 Top N 商品（CDP）。"""
    limit = top_n if top_n is not None else _default_top_n()
    parsed = Alibaba1688UrlParser().parse(shop_url)
    if parsed.type is not Alibaba1688UrlType.SHOP:
        raise ValueError("请粘贴 1688 店铺链接（如 https://shopXXXX.1688.com/）")

    params = {
        "url": parsed.source_url,
        "top_n": limit,
        "shop_host": parsed.shop_host,
    }
    task = create_1688_collection_task("shop", params, source_url=parsed.source_url)
    try:
        offers = Alibaba1688ShopCollector().collect_shop(parsed.source_url, top_n=limit)
        saved = save_1688_products(int(task["id"]), offers)
        task = finish_collection_task(
            int(task["id"]),
            status="completed",
            total_count=len(saved),
            success_count=len(saved),
            fail_count=0,
        )
        result: dict[str, Any] = {
            "task": task,
            "families": saved,
            "shop_url": parsed.source_url,
            "top_n": limit,
            "count": len(saved),
            "message": f"已采集 1688 店铺 {len(saved)} 个商品",
        }
        auto = (os.getenv("1688_AUTO_PIPELINE") or "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if auto and saved:
            from services.shop_pipeline_service import start_pipeline_from_collection_task

            job = start_pipeline_from_collection_task(int(task["id"]), limit=len(saved))
            result["pipeline_job"] = job
            result["message"] = (
                f"已采集 {len(saved)} 个商品，并启动类目匹配/AI/进审核流水线：{job.get('job_no')}"
            )
        return result
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
