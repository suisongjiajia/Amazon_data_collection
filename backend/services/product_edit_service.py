from __future__ import annotations

from typing import Any

from db.ozon_workflow import (
    create_product_edit,
    delete_product_edit,
    get_product_edit,
    list_product_edits,
    reopen_product_edit,
    submit_product_edit_for_review,
    update_product_edit,
    update_product_edit_variant,
)
from services.ozon_category_resolve_service import ensure_edit_category_ids
from services.ozon_listing_payload import preview_listing


def create_edit(raw_product_family_id: int) -> dict[str, Any]:
    edit = create_product_edit(raw_product_family_id)
    try:
        ensured = ensure_edit_category_ids(int(edit["id"]), force=False)
        return ensured.get("edit") or get_product_edit(int(edit["id"]))
    except Exception as exc:
        attributes = dict(edit.get("attributes") or {})
        attributes["category_resolve_error"] = str(exc)
        return update_product_edit(int(edit["id"]), attributes=attributes)


def apply_ai_suggestion_to_edit(edit_id: int, suggestion: dict[str, Any]) -> dict[str, Any]:
    """将 AI 生成结果写入编辑草稿（标题/描述/卖点/图片/属性/变体价格库存）。"""
    edit = get_product_edit(edit_id)
    current_attrs = dict(edit.get("attributes") or {})
    incoming_attrs = dict(suggestion.get("attributes") or {})
    merged = {**current_attrs, **incoming_attrs}
    for key in ("description_category_id", "type_id"):
        if current_attrs.get(key):
            merged[key] = current_attrs[key]
    if suggestion.get("listing_notes"):
        merged["listing_notes"] = str(suggestion["listing_notes"])

    # 图片：优先用更长的一侧，避免 AI/转存只剩 1 张覆盖掉采集图
    sug_images = [u for u in (suggestion.get("images") or []) if isinstance(u, str) and u.startswith("http")]
    edit_images = [u for u in (edit.get("images") or []) if isinstance(u, str) and u.startswith("http")]
    images = sug_images if len(sug_images) >= len(edit_images) else edit_images
    if len(images) < 5:
        try:
            from db.ozon_catalog import get_ozon_product_family

            family = get_ozon_product_family(int(edit["raw_product_family_id"]))
            pool: list[str] = []
            raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
            for url in list(raw.get("images") or []) + list(family.get("bullet_points") or []):
                if isinstance(url, str) and url.startswith("http") and url not in pool:
                    pool.append(url)
            for url in pool:
                if url not in images:
                    images.append(url)
                if len(images) >= 10:
                    break
        except Exception:
            pass

    update_product_edit(
        edit_id,
        title=str(suggestion.get("title") or edit.get("title") or "").strip() or edit.get("title"),
        description=str(suggestion.get("description") or edit.get("description") or ""),
        bullet_points=list(suggestion.get("bullet_points") or edit.get("bullet_points") or []),
        images=images[:15],
        attributes=merged,
        status="editing",
        clear_listing=True,
    )

    variants = list(edit.get("variants") or [])
    sug_variants = list(suggestion.get("variants") or [])
    sug_prices = [item.get("price") for item in sug_variants if item.get("price") is not None]
    uniform_base = sug_prices[0] if sug_prices and all(price == sug_prices[0] for price in sug_prices) else None
    scaled_prices: list[int] = []
    if uniform_base is not None:
        from db.ozon_catalog import get_ozon_product_family
        from services.ozon_pricing_service import variant_prices_from_collected

        family = get_ozon_product_family(int(edit["raw_product_family_id"]))
        price_text_by_ext = {
            str(item.get("external_id") or ""): item.get("price_text")
            for item in (family.get("variants") or [])
        }
        priced_rows = []
        for variant in variants:
            sku = str(variant.get("sku") or "")
            external_id = (
                sku[6:]
                if sku.startswith("A1688-")
                else sku[5:]
                if sku.startswith("OZON-")
                else sku
            )
            priced_rows.append(
                {
                    "external_id": external_id,
                    "price_text": price_text_by_ext.get(external_id),
                }
            )
        scaled_prices = variant_prices_from_collected(
            int(round(float(uniform_base))),
            priced_rows,
            anchor_external_id=str(edit.get("family_external_id") or ""),
        )

    for index, variant in enumerate(variants):
        sug = sug_variants[index] if index < len(sug_variants) else {}
        if scaled_prices and index < len(scaled_prices):
            price = float(scaled_prices[index])
        elif sug.get("price") is not None:
            price = float(sug["price"])
        else:
            price = None
        update_product_edit_variant(
            int(variant["id"]),
            title=str(sug.get("title") or variant.get("title") or suggestion.get("title") or ""),
            price=price,
            quantity=int(sug["quantity"]) if sug.get("quantity") is not None else None,
        )
    return get_product_edit(edit_id)


def get_edit(edit_id: int) -> dict[str, Any]:
    return get_product_edit(edit_id)


def list_edits(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return list_product_edits(status, limit)


def update_edit(
    edit_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    bullet_points: list[str] | None = None,
    images: list[str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return update_product_edit(
        edit_id,
        title=title,
        description=description,
        bullet_points=bullet_points,
        images=images,
        attributes=attributes,
    )


def update_variant(
    variant_id: int,
    *,
    title: str | None = None,
    price: float | None = None,
    quantity: int | None = None,
    image_url: str | None = None,
    variant_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return update_product_edit_variant(
        variant_id,
        title=title,
        price=price,
        quantity=quantity,
        image_url=image_url,
        variant_attributes=variant_attributes,
    )


def preview_edit_listing(edit_id: int) -> dict[str, Any]:
    try:
        ensure_edit_category_ids(edit_id, force=False)
    except Exception:
        pass
    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    return {
        **preview,
        "edit_id": edit_id,
        "edit_status": edit.get("status"),
        "listing_built_at": edit.get("listing_built_at"),
        "saved_listing": edit.get("listing_payload"),
    }


def build_listing(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    if edit["status"] not in ("draft", "editing", "rejected", "listing_ready"):
        raise ValueError("当前状态不可生成 Listing，请先重新打开编辑")

    try:
        ensured = ensure_edit_category_ids(edit_id, force=False)
        edit = ensured.get("edit") or get_product_edit(edit_id)
    except Exception as exc:
        raise ValueError(
            f"自动获取 type_id / description_category_id 失败：{exc}。"
            "请运行 start-ozon-chrome.ps1，在调试 Chrome 登录 seller.ozon.ru 后重试"
            "（并确认已配置 OZON_SELLER_CLIENT_ID）"
        ) from exc

    # 生成 Listing 前统一写入 100×100×100mm / 200g
    from services.ozon_listing_payload import apply_fixed_package_attributes, force_package_metrics_enabled

    if force_package_metrics_enabled():
        attrs = apply_fixed_package_attributes(edit.get("attributes") or {})
        edit = update_product_edit(edit_id, attributes=attrs)

    preview = preview_listing(edit)
    if not preview["ok"]:
        return {
            **preview,
            "edit_id": edit_id,
            "edit": edit,
            "saved": False,
        }
    snapshot = {
        "summary": preview["summary"],
        "payload_items": preview["payload_items"],
        "stock_items": preview["stock_items"],
        "issues": preview["issues"],
    }
    updated = update_product_edit(
        edit_id,
        listing_payload=snapshot,
        status="listing_ready",
        set_listing_built=True,
    )
    return {
        **preview,
        "edit_id": edit_id,
        "edit": updated,
        "saved": True,
    }


def resolve_category(edit_id: int, *, force: bool = True) -> dict[str, Any]:
    """编辑页自动获取类目/类型。"""
    return ensure_edit_category_ids(edit_id, force=force)


def submit_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    if not preview["ok"]:
        messages = "; ".join(
            item["message"] for item in preview["issues"] if item.get("severity") == "error"
        )
        raise ValueError(f"Listing 校验未通过：{messages or '存在错误'}")
    if edit["status"] != "listing_ready" or not edit.get("listing_payload"):
        raise ValueError("请先生成 Listing（校验通过并保存快照）后再提交审核")
    return submit_product_edit_for_review(edit_id)


def reopen_edit(edit_id: int) -> dict[str, Any]:
    return reopen_product_edit(edit_id)


def delete_edit(edit_id: int) -> dict[str, Any]:
    return delete_product_edit(edit_id)


def rescale_flat_edit_variant_prices() -> int:
    """已生成的编辑里，各规格售价相同但采集标价不同时，按标价比例重算。"""
    from db.ozon_catalog import get_ozon_product_family
    from services.ozon_pricing_service import variant_prices_from_collected

    updated = 0
    for edit in list_product_edits(limit=500):
        variants = list(edit.get("variants") or [])
        amounts = [variant.get("price") for variant in variants if variant.get("price") is not None]
        if len(amounts) < 2:
            continue
        if len({float(amount) for amount in amounts}) != 1:
            continue
        family = get_ozon_product_family(int(edit["raw_product_family_id"]))
        price_text_by_ext = {
            str(item.get("external_id") or ""): item.get("price_text")
            for item in (family.get("variants") or [])
        }
        rows = []
        for variant in variants:
            sku = str(variant.get("sku") or "")
            external_id = (
                sku[6:]
                if sku.startswith("A1688-")
                else sku[5:]
                if sku.startswith("OZON-")
                else sku
            )
            rows.append({"external_id": external_id, "price_text": price_text_by_ext.get(external_id)})
        scaled = variant_prices_from_collected(
            int(round(float(amounts[0]))),
            rows,
            anchor_external_id=str(edit.get("family_external_id") or ""),
        )
        if scaled == [int(round(float(amount))) for amount in amounts]:
            continue
        for variant, price in zip(variants, scaled):
            if int(round(float(variant.get("price") or 0))) == price:
                continue
            update_product_edit_variant(int(variant["id"]), price=float(price))
            updated += 1
    return updated
