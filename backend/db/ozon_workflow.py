from __future__ import annotations

from datetime import datetime
from typing import Any

from db.connection import get_connection
from db.helpers import build_code
from db.serialization import fetch_all, fetch_one, to_json


def _attach_edit_variants(edit: dict[str, Any]) -> dict[str, Any]:
    edit["variants"] = fetch_all(
        "SELECT * FROM product_edit_variant WHERE edit_id = %s ORDER BY id",
        (edit["id"],),
    )
    return edit


def create_sourcing_task(raw_product_family_id: int, image_url: str) -> dict[str, Any]:
    task_no = build_code("SRC")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sourcing_task (
                    task_no, raw_product_family_id, image_url, status, started_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (task_no, raw_product_family_id, image_url, "running", datetime.now()),
            )
            task_id = cursor.lastrowid
    return get_sourcing_task(task_id)


def finish_sourcing_task(
    task_id: int,
    *,
    status: str,
    candidate_count: int,
    error_message: str | None = None,
) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE sourcing_task
                SET status = %s,
                    candidate_count = %s,
                    error_message = %s,
                    finished_at = %s
                WHERE id = %s
                """,
                (status, candidate_count, error_message, datetime.now(), task_id),
            )
    return get_sourcing_task(task_id)


def get_sourcing_task(task_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM sourcing_task WHERE id = %s", (task_id,))
    if record is None:
        raise ValueError(f"Sourcing task {task_id} was not found")
    return record


def list_sourcing_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT * FROM sourcing_task ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def save_supplier_candidates(
    raw_product_family_id: int,
    candidates: list[dict[str, Any]],
    *,
    sourcing_task_id: int | None = None,
) -> list[dict[str, Any]]:
    candidate_ids: list[int] = []
    with get_connection() as connection:
        with connection.cursor() as cursor:
            for candidate in candidates:
                cursor.execute(
                    """
                    INSERT INTO supplier_candidate (
                        sourcing_task_id,
                        raw_product_family_id,
                        supplier_name,
                        shop_name,
                        product_title,
                        product_url,
                        image_url,
                        price_text,
                        min_order_qty,
                        match_score,
                        status,
                        raw_payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        sourcing_task_id,
                        raw_product_family_id,
                        candidate.get("supplier_name"),
                        candidate.get("shop_name"),
                        candidate.get("product_title"),
                        candidate.get("product_url"),
                        candidate.get("image_url"),
                        candidate.get("price_text"),
                        candidate.get("min_order_qty"),
                        candidate.get("match_score"),
                        candidate.get("status", "candidate"),
                        to_json(candidate.get("raw_payload") or {}),
                    ),
                )
                candidate_ids.append(int(cursor.lastrowid))

    return [get_supplier_candidate(candidate_id) for candidate_id in candidate_ids]


def get_supplier_candidate(candidate_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM supplier_candidate WHERE id = %s", (candidate_id,))
    if record is None:
        raise ValueError(f"Supplier candidate {candidate_id} was not found")
    return record


def list_supplier_candidates(
    raw_product_family_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if raw_product_family_id is not None:
        return fetch_all(
            """
            SELECT * FROM supplier_candidate
            WHERE raw_product_family_id = %s
            ORDER BY match_score DESC, created_at DESC
            LIMIT %s
            """,
            (raw_product_family_id, limit),
        )
    return fetch_all(
        "SELECT * FROM supplier_candidate ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def update_supplier_candidate_status(candidate_id: int, status: str) -> dict[str, Any]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE supplier_candidate SET status = %s WHERE id = %s",
                (status, candidate_id),
            )
    return get_supplier_candidate(candidate_id)


def create_product_edit(raw_product_family_id: int) -> dict[str, Any]:
    from db.ozon_catalog import get_ozon_product_family
    from services.ozon_category_resolve_service import resolve_category_for_family
    from services.ozon_pricing_service import DEFAULT_STOCK_QTY, suggest_price_for_family

    family = get_ozon_product_family(raw_product_family_id)
    is_1688 = str(family.get("platform") or "") == "1688"

    # 创建编辑前尽量自动补全类目/类型；1688 走标题匹配，Ozon 走 resolve/by-sku
    try:
        if is_1688:
            from services.ozon_category_match_service import match_category_for_family

            match_category_for_family(raw_product_family_id, force=False)
            family = get_ozon_product_family(raw_product_family_id)
        else:
            resolve_category_for_family(raw_product_family_id, force=False)
            family = get_ozon_product_family(raw_product_family_id)
    except Exception:
        pass

    raw = family.get("raw_payload") or {}
    if not isinstance(raw, dict):
        raw = {}
    inner = raw.get("rawPayload") or {}
    if not isinstance(inner, dict):
        inner = {}
    details = inner.get("details") or raw.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    images = list(details.get("images") or raw.get("images") or [])
    if isinstance(family.get("bullet_points"), list):
        for url in family.get("bullet_points") or []:
            if isinstance(url, str) and url.startswith("http") and url not in images:
                images.append(url)
    if not images and family.get("main_image_url"):
        images = [family.get("main_image_url")]

    attributes: dict[str, Any] = dict(details.get("attributes") or raw.get("attributes") or {})
    # 列表/编辑属性不塞整张包装表（体积大，易撑爆 MySQL sort buffer）
    attributes.pop("pack_rows", None)
    description_category_id = (
        family.get("category_id")
        or details.get("description_category_id")
        or details.get("category_id")
    )
    type_id = family.get("type_id") or details.get("type_id")
    if description_category_id:
        attributes["description_category_id"] = str(description_category_id)
    if type_id:
        attributes["type_id"] = str(type_id)
    if details.get("size"):
        attributes.setdefault("size", details["size"])
    if details.get("weight"):
        attributes.setdefault("weight", details["weight"])
    attributes.setdefault("brand_mode", "no_brand")
    attributes.setdefault("fulfillment", "rFBS")
    if is_1688:
        attributes.setdefault("source_platform", "1688")
        # 双区分项：采集时 color 已合成「款式 · 尺码」，合卡按颜色轴区分
        family_variants = family.get("variants") or []
        has_distinguished = any(
            str(v.get("color") or (v.get("variant_attributes") or {}).get("区分项") or "").strip()
            for v in family_variants
        )
        if has_distinguished:
            attributes.setdefault("variant_aspect", "color")
        # 1688：优先用详情页包装尺寸/重量，避免被统一默认 100×100×100/200g 覆盖
        from collector.alibaba1688.package_parse import extract_package_metrics
        from services.ozon_listing_payload import package_is_manual

        detail_blob = {}
        nested_raw = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
        if isinstance(nested_raw.get("detail"), dict):
            detail_blob = nested_raw["detail"]
        elif isinstance(raw.get("detail"), dict):
            detail_blob = raw["detail"]
        package_metrics = {}
        if isinstance(nested_raw.get("package_metrics"), dict):
            package_metrics = nested_raw["package_metrics"]
        elif isinstance(raw.get("package_metrics"), dict):
            package_metrics = raw["package_metrics"]
        if not package_metrics:
            package_metrics = extract_package_metrics(attributes=attributes, detail=detail_blob)
        if package_metrics.get("depth_mm") and package_metrics.get("width_mm") and package_metrics.get("height_mm"):
            d, w, h = (
                int(package_metrics["depth_mm"]),
                int(package_metrics["width_mm"]),
                int(package_metrics["height_mm"]),
            )
            attributes["Длина, мм"] = str(d)
            attributes["Ширина, мм"] = str(w)
            attributes["Высота, мм"] = str(h)
            attributes["depth_mm"] = str(d)
            attributes["width_mm"] = str(w)
            attributes["height_mm"] = str(h)
            attributes["length_mm"] = str(d)
            attributes["Размеры, мм"] = f"{d}*{w}*{h}"
            attributes["Размер упаковки (Длина х Ширина х Высота), см"] = (
                f"{max(1, round(d / 10))}x{max(1, round(w / 10))}x{max(1, round(h / 10))}"
            )
        if package_metrics.get("weight_g"):
            wg = int(package_metrics["weight_g"])
            attributes["Вес, г"] = str(wg)
            attributes["Вес товара, г"] = str(wg)
            attributes["Вес с упаковкой, г"] = str(wg)
            attributes["weight_g"] = str(wg)
            attributes["weight"] = str(wg)
        if package_metrics and not package_is_manual(attributes):
            attributes["package_manual"] = "1"
            attributes["package_source"] = "1688_detail"
    # 全站统一包裹：100×100×100 mm / 200g（手改 / 1688 详情已写入则跳过）
    from services.ozon_listing_payload import apply_fixed_package_attributes

    attributes = apply_fixed_package_attributes(attributes)

    initial_qty = DEFAULT_STOCK_QTY
    initial_price = None
    scaled_prices: list[int] = []
    try:
        priced = suggest_price_for_family(raw_product_family_id)
        initial_price = priced["pricing"]["list_price"]
        initial_qty = priced["pricing"]["stock_qty"]
        from services.ozon_pricing_service import variant_prices_from_collected

        scaled_prices = variant_prices_from_collected(
            int(initial_price),
            list(family.get("variants") or []),
            anchor_external_id=str(family.get("external_id") or ""),
        )
        attributes["pricing_formula"] = priced["pricing"]["formula"]
        attributes["currency_code"] = priced["pricing"]["currency_code"]
        attributes["freight_channel"] = priced["freight"]["channel_name"]
        attributes["freight_cny"] = str(priced["freight"]["freight_cny"])
    except Exception as exc:
        attributes["pricing_error"] = str(exc)

    description = (details.get("description") or "").strip()
    sku_prefix = "A1688-" if is_1688 else "OZON-"

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO product_edit (
                    raw_product_family_id,
                    title,
                    description,
                    bullet_points,
                    images,
                    attributes,
                    status,
                    target_platform
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    description = COALESCE(NULLIF(VALUES(description), ''), description),
                    images = VALUES(images),
                    attributes = VALUES(attributes),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    raw_product_family_id,
                    family.get("title") or "未命名商品",
                    description,
                    to_json(family.get("bullet_points") or []),
                    to_json(images),
                    to_json(attributes),
                    "draft",
                    "ozon",
                ),
            )
            cursor.execute(
                "SELECT id FROM product_edit WHERE raw_product_family_id = %s",
                (raw_product_family_id,),
            )
            edit_id = int(cursor.fetchone()[0])

            kept_skus: list[str] = []
            for index, variant in enumerate(family.get("variants") or []):
                sku = f"{sku_prefix}{variant.get('external_id') or variant['id']}"
                variant_price = scaled_prices[index] if index < len(scaled_prices) else initial_price
                va = dict(variant.get("variant_attributes") or {})
                # 每个变体独立 listing：确保有完整主图+副图
                own = va.get("images")
                if not isinstance(own, list) or not own:
                    built: list[str] = []
                    primary = str(variant.get("main_image_url") or "").strip()
                    if primary:
                        built.append(primary)
                    for url in images:
                        text = str(url or "").strip()
                        if text and text not in built:
                            built.append(text)
                    va["images"] = built[:15]
                    if built:
                        va["image_url"] = built[0]
                cursor.execute(
                    """
                    INSERT INTO product_edit_variant (
                        edit_id,
                        raw_product_variant_id,
                        sku,
                        title,
                        price,
                        quantity,
                        image_url,
                        variant_attributes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        title = COALESCE(VALUES(title), title),
                        price = VALUES(price),
                        quantity = VALUES(quantity),
                        image_url = VALUES(image_url),
                        variant_attributes = COALESCE(VALUES(variant_attributes), variant_attributes),
                        raw_product_variant_id = VALUES(raw_product_variant_id),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        edit_id,
                        variant["id"],
                        sku,
                        variant.get("title"),
                        variant_price,
                        initial_qty,
                        variant.get("main_image_url") or (va.get("images") or [None])[0],
                        to_json(va),
                    ),
                )
                kept_skus.append(sku)

            if kept_skus:
                placeholders = ", ".join(["%s"] * len(kept_skus))
                cursor.execute(
                    f"""
                    DELETE FROM product_edit_variant
                    WHERE edit_id = %s AND sku NOT IN ({placeholders})
                    """,
                    (edit_id, *kept_skus),
                )
            else:
                cursor.execute(
                    "DELETE FROM product_edit_variant WHERE edit_id = %s",
                    (edit_id,),
                )

    return get_product_edit(edit_id)


def get_product_edit(edit_id: int) -> dict[str, Any]:
    record = fetch_one(
        """
        SELECT pe.*, rf.title AS family_title, rf.main_image_url AS family_main_image_url,
               rf.sales_rank, rf.category_name, rf.external_id AS family_external_id,
               rf.source_url AS family_source_url
        FROM product_edit pe
        JOIN raw_product_family rf ON rf.id = pe.raw_product_family_id
        WHERE pe.id = %s
        """,
        (edit_id,),
    )
    if record is None:
        raise ValueError(f"Product edit {edit_id} was not found")
    return _attach_edit_variants(record)


def list_product_edits(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """列表查询：先按 id 轻量排序，再取详情，避免 pe.* + ORDER BY 撑爆 MySQL sort buffer。"""
    limit = max(1, min(int(limit), 200))
    if status:
        id_rows = fetch_all(
            """
            SELECT pe.id
            FROM product_edit pe
            WHERE pe.status = %s
            ORDER BY pe.updated_at DESC, pe.id DESC
            LIMIT %s
            """,
            (status, limit),
        )
    else:
        id_rows = fetch_all(
            """
            SELECT pe.id
            FROM product_edit pe
            ORDER BY pe.updated_at DESC, pe.id DESC
            LIMIT %s
            """,
            (limit,),
        )
    edit_ids = [int(row["id"]) for row in id_rows if row.get("id") is not None]
    if not edit_ids:
        return []

    placeholders = ", ".join(["%s"] * len(edit_ids))
    # 列表不取 listing_payload（体积大且列表页不用）
    edits = fetch_all(
        f"""
        SELECT
            pe.id,
            pe.raw_product_family_id,
            pe.title,
            pe.description,
            pe.bullet_points,
            pe.images,
            pe.attributes,
            pe.status,
            pe.target_platform,
            pe.listing_built_at,
            pe.created_at,
            pe.updated_at,
            rf.title AS family_title,
            rf.main_image_url AS family_main_image_url,
            rf.sales_rank,
            rf.category_name,
            rf.external_id AS family_external_id,
            rf.source_url AS family_source_url
        FROM product_edit pe
        JOIN raw_product_family rf ON rf.id = pe.raw_product_family_id
        WHERE pe.id IN ({placeholders})
        """,
        tuple(edit_ids),
    )
    by_id = {int(edit["id"]): edit for edit in edits}
    ordered = [by_id[edit_id] for edit_id in edit_ids if edit_id in by_id]
    return [_attach_edit_variants(edit) for edit in ordered]


def update_product_edit(
    edit_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    bullet_points: list[str] | None = None,
    images: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
    status: str | None = None,
    listing_payload: dict[str, Any] | None = None,
    clear_listing: bool = False,
    set_listing_built: bool = False,
) -> dict[str, Any]:
    current = get_product_edit(edit_id)
    fields: list[str] = []
    values: list[Any] = []
    content_changed = False

    if title is not None:
        fields.append("title = %s")
        values.append(title)
        content_changed = True
    if description is not None:
        fields.append("description = %s")
        values.append(description)
        content_changed = True
    if bullet_points is not None:
        fields.append("bullet_points = %s")
        values.append(to_json(bullet_points))
        content_changed = True
    if images is not None:
        fields.append("images = %s")
        values.append(to_json(images))
        content_changed = True
    if attributes is not None:
        fields.append("attributes = %s")
        values.append(to_json(attributes))
        content_changed = True
    if listing_payload is not None:
        fields.append("listing_payload = %s")
        values.append(to_json(listing_payload))
    if set_listing_built:
        fields.append("listing_built_at = %s")
        values.append(datetime.now())
    elif clear_listing or (content_changed and listing_payload is None):
        fields.append("listing_payload = NULL")
        fields.append("listing_built_at = NULL")
        if status is None and current.get("status") == "listing_ready":
            status = "editing"
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if not fields:
        return current

    values.append(edit_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE product_edit SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
    return get_product_edit(edit_id)


def update_product_edit_variant(
    variant_id: int,
    *,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
    image_url: str | None = None,
    variant_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = %s")
        values.append(title)
    if price is not None:
        fields.append("price = %s")
        values.append(price)
    if quantity is not None:
        fields.append("quantity = %s")
        values.append(quantity)
    if image_url is not None:
        fields.append("image_url = %s")
        values.append(image_url)
    if variant_attributes is not None:
        fields.append("variant_attributes = %s")
        values.append(to_json(variant_attributes))
    if not fields:
        record = fetch_one("SELECT * FROM product_edit_variant WHERE id = %s", (variant_id,))
        if record is None:
            raise ValueError(f"Product edit variant {variant_id} was not found")
        return record

    values.append(variant_id)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE product_edit_variant SET {', '.join(fields)} WHERE id = %s",
                tuple(values),
            )
            cursor.execute(
                "SELECT edit_id FROM product_edit_variant WHERE id = %s",
                (variant_id,),
            )
            row = cursor.fetchone()
            edit_id = int(row[0]) if row else None
    if edit_id is not None:
        edit = get_product_edit(edit_id)
        if edit.get("status") == "listing_ready" or edit.get("listing_payload"):
            update_product_edit(edit_id, clear_listing=True, status="editing" if edit.get("status") == "listing_ready" else None)
    record = fetch_one("SELECT * FROM product_edit_variant WHERE id = %s", (variant_id,))
    if record is None:
        raise ValueError(f"Product edit variant {variant_id} was not found")
    return record


def submit_product_edit_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in ("listing_ready",):
        raise ValueError("请先生成并校验 Listing，通过后再提交审核")
    if not edit.get("listing_payload"):
        raise ValueError("缺少 Listing 快照，请先点击「生成 Listing」")
    return update_product_edit(edit_id, status="pending_review", clear_listing=False)


def reopen_product_edit(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in (
        "listing_ready",
        "pending_review",
        "needs_fix",
        "approved",
        "rejected",
        "published",
    ):
        raise ValueError("当前状态不可重新打开编辑")
    return update_product_edit(edit_id, status="editing", clear_listing=True)


def delete_product_edit(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in ("draft", "editing", "rejected", "listing_ready", "needs_fix"):
        raise ValueError("待审核、已通过或已发布的编辑不能取消")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM product_edit WHERE id = %s", (edit_id,))
    return {"id": edit_id, "deleted": True}


def create_review_record(
    edit_id: int,
    *,
    result: str,
    note: str | None = None,
    reviewer: str | None = None,
    auto_reviewed: bool = False,
) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    status = str(edit.get("status") or "")
    if result == "approved":
        if status != "pending_review":
            raise ValueError("仅待审核 Listing 可审批通过（待修复请先改完再提交审核）")
    elif result == "rejected":
        if status not in {"pending_review", "needs_fix"}:
            raise ValueError("仅待审核或待修复 Listing 可驳回")
    else:
        raise ValueError(f"未知审核结果：{result}")
    new_status = "approved" if result == "approved" else "rejected"
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO review_record (edit_id, result, note, reviewer, auto_reviewed)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (edit_id, result, note, reviewer, 1 if auto_reviewed else 0),
            )
            review_id = int(cursor.lastrowid)
            cursor.execute(
                "UPDATE product_edit SET status = %s WHERE id = %s",
                (new_status, edit_id),
            )
    return get_review_record(review_id)


def get_review_record(review_id: int) -> dict[str, Any]:
    record = fetch_one("SELECT * FROM review_record WHERE id = %s", (review_id,))
    if record is None:
        raise ValueError(f"Review record {review_id} was not found")
    return record


def list_review_records(edit_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if edit_id is not None:
        return fetch_all(
            "SELECT * FROM review_record WHERE edit_id = %s ORDER BY created_at DESC LIMIT %s",
            (edit_id, limit),
        )
    return fetch_all(
        "SELECT * FROM review_record ORDER BY created_at DESC LIMIT %s",
        (limit,),
    )


def create_ozon_publish_task(edit_id: int, *, shop_name: str | None = None) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] != "approved":
        raise ValueError("仅审核通过的 Listing 可发布")

    task_no = build_code("OZPUB")
    with get_connection() as connection:
        with connection.cursor() as cursor:
            # 同一编辑只保留一条进行中任务：旧任务标为 superseded，避免列表重复
            cursor.execute(
                """
                UPDATE ozon_publish_task
                SET status = 'superseded',
                    error_message = COALESCE(
                        NULLIF(error_message, ''),
                        '已被新的发布任务替代'
                    ),
                    finished_at = COALESCE(finished_at, %s)
                WHERE edit_id = %s
                  AND status NOT IN ('listed', 'completed', 'superseded')
                """,
                (datetime.now(), edit_id),
            )
            cursor.execute(
                """
                INSERT INTO ozon_publish_task (
                    task_no, edit_id, shop_name, status, submit_type, submitted_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (task_no, edit_id, shop_name, "running", "api", datetime.now()),
            )
            task_id = int(cursor.lastrowid)
            variants = edit.get("variants") or []
            for variant in variants:
                cursor.execute(
                    """
                    INSERT INTO ozon_publish_item (
                        task_id, edit_variant_id, seller_sku, status
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (task_id, variant["id"], variant["sku"], "pending"),
                )

            cursor.execute(
                "UPDATE ozon_publish_task SET total_count = %s WHERE id = %s",
                (len(variants), task_id),
            )

    return get_ozon_publish_task(task_id)


def get_ozon_publish_task(task_id: int) -> dict[str, Any]:
    task = fetch_one(
        """
        SELECT opt.*, pe.title AS edit_title, pe.status AS edit_status, pe.images AS edit_images,
               rf.main_image_url AS main_image_url, rf.title AS family_title,
               rf.external_id AS family_external_id
        FROM ozon_publish_task opt
        JOIN product_edit pe ON pe.id = opt.edit_id
        JOIN raw_product_family rf ON rf.id = pe.raw_product_family_id
        WHERE opt.id = %s
        """,
        (task_id,),
    )
    if task is None:
        raise ValueError(f"Ozon publish task {task_id} was not found")
    task["items"] = fetch_all(
        "SELECT * FROM ozon_publish_item WHERE task_id = %s ORDER BY id",
        (task_id,),
    )
    return task


def list_ozon_publish_tasks(limit: int = 50) -> list[dict[str, Any]]:
    """每个 edit_id 只返回最新一条任务，避免同商品多行刷屏。"""
    tasks = fetch_all(
        """
        SELECT t.*, pe.title AS edit_title, pe.status AS edit_status, pe.images AS edit_images,
               rf.main_image_url AS main_image_url, rf.title AS family_title,
               rf.external_id AS family_external_id
        FROM (
            SELECT opt.*,
                   ROW_NUMBER() OVER (PARTITION BY opt.edit_id ORDER BY opt.created_at DESC, opt.id DESC) AS rn
            FROM ozon_publish_task opt
            WHERE opt.status <> 'superseded'
        ) t
        JOIN product_edit pe ON pe.id = t.edit_id
        JOIN raw_product_family rf ON rf.id = pe.raw_product_family_id
        WHERE t.rn = 1
        ORDER BY t.created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    for task in tasks:
        task.pop("rn", None)
        task["items"] = fetch_all(
            "SELECT * FROM ozon_publish_item WHERE task_id = %s ORDER BY id",
            (task["id"],),
        )
    return tasks
