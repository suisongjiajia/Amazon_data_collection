from __future__ import annotations

from typing import Any

from db.connection import get_connection
from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import (
    create_review_record,
    get_product_edit,
    list_review_records,
    list_supplier_candidates,
    update_product_edit,
)
from db.shop_pipeline import find_pipeline_item_by_edit
from services.ozon_listing_payload import _package_density_issue, preview_listing
from services.sourcing_service import _enrich_ozon_family_for_display


def approve(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    record = create_review_record(edit_id, result="approved", note=note, reviewer=reviewer)
    from db.shop_pipeline import sync_pipeline_items_for_review

    sync_pipeline_items_for_review(edit_id, result="approved", note=note)
    return {"review": record, "edit": get_product_edit(edit_id)}


def reject(edit_id: int, *, note: str | None = None, reviewer: str | None = "owner") -> dict[str, Any]:
    record = create_review_record(edit_id, result="rejected", note=note, reviewer=reviewer)
    from db.shop_pipeline import sync_pipeline_items_for_review

    sync_pipeline_items_for_review(edit_id, result="rejected", note=note)
    return {"review": record, "edit": get_product_edit(edit_id)}


def list_records(edit_id: int | None = None, limit: int = 50) -> list[dict]:
    return list_review_records(edit_id, limit)


def update_prices(
    edit_id: int,
    *,
    apply_all_price: float | None = None,
    variant_prices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """审核中改价：更新变体售价并重建 Listing 快照，保持/升为 pending_review。"""
    edit = get_product_edit(edit_id)
    status = str(edit.get("status") or "")
    if status not in {"pending_review", "needs_fix"}:
        raise ValueError("仅待审核或待修复的商品可在审核中心改价")

    variants = list(edit.get("variants") or [])
    if not variants:
        raise ValueError("没有可改价的变体")

    price_map: dict[int, float] = {}
    if apply_all_price is not None:
        if float(apply_all_price) <= 0:
            raise ValueError("售价必须大于 0")
        for variant in variants:
            price_map[int(variant["id"])] = float(apply_all_price)
    for item in variant_prices or []:
        vid = int(item["variant_id"])
        price = float(item["price"])
        if price <= 0:
            raise ValueError(f"变体 {vid} 售价必须大于 0")
        price_map[vid] = price

    if not price_map:
        raise ValueError("请提供 apply_all_price 或 variant_prices")

    allowed_ids = {int(v["id"]) for v in variants}
    unknown = [vid for vid in price_map if vid not in allowed_ids]
    if unknown:
        raise ValueError(f"变体不属于该编辑草稿：{unknown}")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for variant_id, price in price_map.items():
                cursor.execute(
                    "UPDATE product_edit_variant SET price = %s WHERE id = %s AND edit_id = %s",
                    (price, variant_id, edit_id),
                )

    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    if not preview["ok"]:
        messages = "; ".join(
            issue.get("message") or ""
            for issue in (preview.get("issues") or [])
            if issue.get("severity") == "error"
        )
        return {
            "ok": False,
            "saved_prices": True,
            "listing_rebuilt": False,
            "message": messages or "价格已保存，但 Listing 校验未通过",
            "edit": edit,
            "preview": preview,
            "bundle": get_listing_for_review(edit_id),
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
        status="pending_review",
        set_listing_built=True,
    )
    return {
        "ok": True,
        "saved_prices": True,
        "listing_rebuilt": True,
        "message": "价格已更新并写入 Listing",
        "edit": updated,
        "preview": preview,
        "bundle": get_listing_for_review(edit_id),
    }


def _apply_net_product_size(
    attrs: dict[str, Any],
    *,
    net_depth_mm: int | None,
    net_width_mm: int | None,
    net_height_mm: int | None,
) -> None:
    """净品尺寸单独保存，不覆盖包裹长宽高。留空则清掉净品。"""
    values = (net_depth_mm, net_width_mm, net_height_mm)
    if all(value is None or int(value) <= 0 for value in values):
        for key in ("net_depth_mm", "net_width_mm", "net_height_mm", "Размеры товара, мм"):
            attrs.pop(key, None)
        depth = attrs.get("depth_mm") or attrs.get("Длина, мм")
        width = attrs.get("width_mm") or attrs.get("Ширина, мм")
        height = attrs.get("height_mm") or attrs.get("Высота, мм")
        if depth and width and height:
            attrs["Размеры, мм"] = f"{depth}*{width}*{height}"
        return
    if not all(value and int(value) > 0 for value in values):
        raise ValueError("净品长、宽、高要一起填写，且必须大于 0")
    depth, width, height = int(net_depth_mm), int(net_width_mm), int(net_height_mm)
    text = f"{depth}*{width}*{height}"
    attrs["net_depth_mm"] = str(depth)
    attrs["net_width_mm"] = str(width)
    attrs["net_height_mm"] = str(height)
    attrs["Размеры товара, мм"] = text
    attrs["Размеры, мм"] = text


def _clean_listing_images(images: list[str] | None) -> list[str] | None:
    if images is None:
        return None
    cleaned: list[str] = []
    for raw in images:
        text = str(raw or "").strip()
        if not text.lower().startswith(("http://", "https://")):
            continue
        if text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("至少保留 1 张图片")
    return cleaned[:15]


def _clean_variant_images(images: list[str] | None) -> list[str]:
    """变体图集可为空（上架时会再拼商品共用附图）。"""
    if not images:
        return []
    cleaned: list[str] = []
    for raw in images:
        text = str(raw or "").strip()
        if not text.lower().startswith(("http://", "https://")):
            continue
        if text not in cleaned:
            cleaned.append(text)
    return cleaned[:15]


def update_content(
    edit_id: int,
    *,
    depth_mm: int | None = None,
    width_mm: int | None = None,
    height_mm: int | None = None,
    weight_g: int | None = None,
    net_depth_mm: int | None = None,
    net_width_mm: int | None = None,
    net_height_mm: int | None = None,
    images: list[str] | None = None,
    variant_aspect: str | None = None,
    variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """审核中心改图片、包裹尺寸、净品尺寸、颜色、库存和价格。"""
    from db.ozon_workflow import update_product_edit_variant

    edit = get_product_edit(edit_id)
    status = str(edit.get("status") or "")
    if status not in {"pending_review", "needs_fix"}:
        raise ValueError("仅待审核或待修复的商品可在审核中心修改")

    attrs = dict(edit.get("attributes") or {})
    aspect = str(variant_aspect or attrs.get("variant_aspect") or "color").strip().lower()
    if aspect not in {"color", "size"}:
        aspect = "color"
    attrs["variant_aspect"] = aspect
    if any(value is not None for value in (depth_mm, width_mm, height_mm, weight_g)):
        if not all(value and int(value) > 0 for value in (depth_mm, width_mm, height_mm, weight_g)):
            raise ValueError("长、宽、高、重量都要填写，且必须大于 0")
        depth, width, height, weight = int(depth_mm), int(width_mm), int(height_mm), int(weight_g)
        density = _package_density_issue(depth, width, height, weight)
        if density:
            raise ValueError(str(density["message"]))
        attrs["package_manual"] = "1"
        attrs["Длина, мм"] = str(depth)
        attrs["Ширина, мм"] = str(width)
        attrs["Высота, мм"] = str(height)
        attrs["Вес, г"] = str(weight)
        attrs["Вес товара, г"] = str(weight)
        attrs["Вес с упаковкой, г"] = str(weight)
        attrs["depth_mm"] = str(depth)
        attrs["width_mm"] = str(width)
        attrs["height_mm"] = str(height)
        attrs["length_mm"] = str(depth)
        attrs["weight_g"] = str(weight)
        attrs["weight"] = str(weight)
        attrs["Размеры, мм"] = f"{depth}*{width}*{height}"
    _apply_net_product_size(
        attrs,
        net_depth_mm=net_depth_mm,
        net_width_mm=net_width_mm,
        net_height_mm=net_height_mm,
    )
    cleaned_images = _clean_listing_images(images)
    update_kwargs: dict[str, Any] = {"attributes": attrs}
    if cleaned_images is not None:
        update_kwargs["images"] = cleaned_images
    update_product_edit(edit_id, **update_kwargs)
    # 注意：不要把变体专属主图强行改成共用图库第一张

    known = {int(v["id"]): v for v in (edit.get("variants") or [])}
    for item in variants or []:
        variant_id = int(item["variant_id"])
        current = known.get(variant_id)
        if current is None:
            raise ValueError(f"变体不属于该商品：{variant_id}")
        va = dict(current.get("variant_attributes") or {})
        color = item.get("color")
        size_text = str(item.get("size") or "").strip()
        # 双区分项：颜色/款式与尺码都保留；合卡区分轴由 variant_aspect 决定
        if color is not None:
            text = str(color).strip()
            if text:
                va["颜色"] = text
                va["款式"] = text.split(" · ")[0].strip() or text
                va["Цвет"] = text
                va["Цвет товара"] = text
                va["Название цвета"] = text
                va["区分项"] = text
            else:
                for key in ("颜色", "款式", "Цвет", "Цвет товара", "Название цвета", "区分项"):
                    va.pop(key, None)
        if size_text:
            va["尺码"] = size_text
            va["Размер"] = size_text
            va["Размер товара"] = size_text
        elif "size" in item:
            for key in ("尺码", "Размер", "Размер товара"):
                va.pop(key, None)
        if aspect == "size":
            # 上架按尺码区分时，颜色属性可留作备注，但主区分用尺码
            if size_text:
                va["区分项"] = size_text
        elif aspect == "color" and color is not None:
            text = str(color).strip()
            if text:
                va["区分项"] = text
        price = item.get("price")
        quantity = item.get("quantity")
        _apply_net_product_size(
            va,
            net_depth_mm=item.get("net_depth_mm"),
            net_width_mm=item.get("net_width_mm"),
            net_height_mm=item.get("net_height_mm"),
        )
        title = str(item.get("title") or "").strip()
        update_kwargs: dict[str, Any] = {
            "title": title or None,
            "price": float(price) if price is not None else None,
            "quantity": int(quantity) if quantity is not None else None,
            "variant_attributes": va,
        }
        if item.get("images") is not None:
            cleaned = _clean_variant_images(list(item.get("images") or []))
            va["images"] = cleaned
            primary = cleaned[0] if cleaned else ""
            if primary:
                va["image_url"] = primary
                update_kwargs["image_url"] = primary
            update_kwargs["variant_attributes"] = va
        elif "image_url" in item and item.get("image_url") is not None:
            image_url = str(item.get("image_url") or "").strip()
            if image_url:
                va["image_url"] = image_url
                update_kwargs["image_url"] = image_url
                update_kwargs["variant_attributes"] = va
        update_product_edit_variant(variant_id, **update_kwargs)

    edit = get_product_edit(edit_id)
    preview = preview_listing(edit)
    if not preview["ok"]:
        messages = "; ".join(
            issue.get("message") or ""
            for issue in (preview.get("issues") or [])
            if issue.get("severity") == "error"
        )
        return {
            "ok": False,
            "listing_rebuilt": False,
            "message": messages or "已保存，但 Listing 仍未通过",
            "edit": edit,
            "preview": preview,
            "bundle": get_listing_for_review(edit_id),
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
        status="pending_review",
        set_listing_built=True,
    )
    return {
        "ok": True,
        "listing_rebuilt": True,
        "message": "已保存并更新 Listing",
        "edit": updated,
        "preview": preview,
        "bundle": get_listing_for_review(edit_id),
    }


def get_listing_for_review(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    family_id = int(edit["raw_product_family_id"])
    family = get_ozon_product_family(family_id)
    product = _enrich_ozon_family_for_display(family)

    candidates = list_supplier_candidates(family_id, limit=20)
    selected = [item for item in candidates if item.get("status") == "selected"]
    others = [item for item in candidates if item.get("status") != "selected"]
    others_sorted = sorted(others, key=lambda c: float(c.get("match_score") or 0), reverse=True)
    suppliers = selected + others_sorted
    suppliers = suppliers[:5] if not selected else selected + others_sorted[: max(0, 5 - len(selected))]

    pipeline_item = find_pipeline_item_by_edit(edit_id)
    stage = (pipeline_item or {}).get("stage_detail") or {}
    pricing = stage.get("pricing")
    attrs = edit.get("attributes") or {}
    price_summary = {
        "list_price": (edit.get("variants") or [{}])[0].get("price"),
        "currency_code": attrs.get("currency_code"),
        "formula": attrs.get("pricing_formula"),
        "freight_cny": attrs.get("freight_cny"),
        "freight_channel": attrs.get("freight_channel"),
        "pricing_error": attrs.get("pricing_error") or attrs.get("pipeline_error"),
    }
    if pricing is None and attrs.get("pricing_formula"):
        pricing = {
            "pricing": {
                "list_price": price_summary["list_price"],
                "formula": attrs.get("pricing_formula"),
                "currency_code": attrs.get("currency_code"),
            },
            "freight": {
                "freight_cny": attrs.get("freight_cny"),
                "channel_name": attrs.get("freight_channel"),
            },
        }

    saved = edit.get("listing_payload")
    if isinstance(saved, dict) and saved.get("summary") is not None:
        preview = {
            "ok": True,
            "issues": saved.get("issues") or [],
            "summary": saved.get("summary") or {},
            "payload_items": saved.get("payload_items") or [],
            "stock_items": saved.get("stock_items") or [],
            "build_error": None,
            "from_snapshot": True,
        }
    else:
        # 展开审核卡片只读库。没有快照时不要现场调 Ozon 类目属性接口，
        # 那会按属性逐个搜字典，一次展开要几十秒。保存时再重建 Listing。
        preview = {
            "ok": False,
            "issues": [],
            "summary": {},
            "payload_items": [],
            "stock_items": [],
            "build_error": None,
            "from_snapshot": False,
        }

    return {
        "edit": edit,
        "preview": preview,
        "saved_listing": saved,
        "product": product,
        "suppliers": suppliers,
        "selected_supplier": selected[0] if selected else (suppliers[0] if suppliers else None),
        "pricing": pricing,
        "price_summary": price_summary,
        "pipeline_item": pipeline_item,
        "pipeline_error": attrs.get("pipeline_error"),
        "failure_kind": attrs.get("failure_kind") or (pipeline_item or {}).get("status"),
    }
