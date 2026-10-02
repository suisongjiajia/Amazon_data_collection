"""校正已上线商品：包装尺寸优先 → 兴远抬重量 → 重算售价 → 推 Ozon。"""
from __future__ import annotations

import logging
import time
from typing import Any

from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import get_product_edit, list_product_edits, update_product_edit, update_product_edit_variant
from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError
from services.ozon_import_status import extract_import_task_id
from services.ozon_listing_payload import build_import_items, read_variant_package_metrics
from services.ozon_pricing_service import (
    is_placeholder_dims,
    is_placeholder_package,
    parse_cny_price,
    suggest_price_for_package,
    write_package_fields,
)
from services.ozon_variant_cost_match import match_cost_by_listing_title
from services.xingyuan_freight import FreightError, normalize_package_for_shipping

logger = logging.getLogger(__name__)


def _sku_external_id(sku: str) -> str:
    text = str(sku or "").strip()
    if text.startswith("A1688-"):
        return text[6:]
    if text.startswith("OZON-"):
        return text[5:]
    return text


def _family_package(family: dict[str, Any]) -> tuple[int | None, int | None, int | None, int | None]:
    raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
    nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
    metrics = nested.get("package_metrics") if isinstance(nested.get("package_metrics"), dict) else {}
    if not metrics and isinstance(raw.get("package_metrics"), dict):
        metrics = raw["package_metrics"]
    try:
        d = int(metrics["depth_mm"]) if metrics.get("depth_mm") else None
        w = int(metrics["width_mm"]) if metrics.get("width_mm") else None
        h = int(metrics["height_mm"]) if metrics.get("height_mm") else None
        wt = int(metrics["weight_g"]) if metrics.get("weight_g") else None
    except (TypeError, ValueError):
        return None, None, None, None
    return d, w, h, wt


def _raw_cost_by_external(family: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in family.get("variants") or []:
        ext = str(row.get("external_id") or "").strip()
        cost = parse_cny_price(row.get("price_text"))
        if not cost:
            va = row.get("variant_attributes") if isinstance(row.get("variant_attributes"), dict) else {}
            cost = parse_cny_price(va.get("price_text"))
        if ext and cost:
            out[ext] = float(cost)
    return out


def _resolve_package(
    edit: dict[str, Any],
    variant: dict[str, Any],
    family: dict[str, Any],
    *,
    matched_weight_g: int | None = None,
) -> tuple[int, int, int, int]:
    attrs = edit.get("attributes") if isinstance(edit.get("attributes"), dict) else {}
    d, w, h, wt = read_variant_package_metrics(attrs, variant)
    fam_d, fam_w, fam_h, fam_wt = _family_package(family)
    from services.ozon_listing_payload import read_package_metrics

    edit_d, edit_w, edit_h, edit_wt = read_package_metrics(attrs)

    # 假立方体尺寸 → 用商品/采集真实外包装
    variant_weight = int(wt) if wt else 0
    if is_placeholder_dims(d, w, h):
        if edit_d and edit_w and edit_h and not is_placeholder_dims(edit_d, edit_w, edit_h):
            d, w, h = edit_d, edit_w, edit_h
        elif fam_d and fam_w and fam_h:
            d, w, h = fam_d, fam_w, fam_h

    # 重量：标题匹配到的 1688 真实重量优先；外套勿沿用整梯残留重货重量
    if matched_weight_g and int(matched_weight_g) > 200:
        wt = int(matched_weight_g)
    elif matched_weight_g is not None and int(matched_weight_g) > 0 and int(matched_weight_g) <= 200:
        # 外套等轻件：用轻重量，交给尺寸档抬到渠道下限
        wt = int(matched_weight_g)
    elif variant_weight > 200:
        wt = variant_weight
    else:
        wt = variant_weight or 200

    if (not d or not w or not h) and fam_d and fam_w and fam_h:
        d, w, h = fam_d, fam_w, fam_h

    if not (d and w and h and wt):
        d = int(d or 200)
        w = int(w or 150)
        h = int(h or 100)
        wt = int(wt or 200)
    return int(d), int(w), int(h), int(wt)


def repair_edit_package_and_prices(edit_id: int, *, dry_run: bool = False) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    family = get_ozon_product_family(int(edit["raw_product_family_id"]))
    costs = _raw_cost_by_external(family)
    # 无变体货本时用商品级建议价货本
    fallback_cost = None
    if costs:
        fallback_cost = min(costs.values())
    else:
        raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
        fallback_cost = parse_cny_price(raw.get("price_text"))

    rows: list[dict[str, Any]] = []
    attrs = dict(edit.get("attributes") or {})
    max_pkg: tuple[int, int, int, int] | None = None

    for variant in edit.get("variants") or []:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        # 关键：按本地标题卖什么匹配货本（整梯不能再用外套货号的 ¥18）
        matched = match_cost_by_listing_title(
            variant,
            family,
            edit_title=str(edit.get("title") or ""),
        )
        ext = _sku_external_id(sku)
        cost = (matched or {}).get("cost") or costs.get(ext) or fallback_cost
        matched_weight = (matched or {}).get("weight_g")
        if not cost:
            raise ValueError(f"{sku}: 缺少 1688 货本，无法重算售价")

        depth, width, height, weight = _resolve_package(
            edit,
            variant,
            family,
            matched_weight_g=int(matched_weight) if matched_weight is not None else None,
        )
        normalized = normalize_package_for_shipping(depth, width, height, weight)
        chargeable = int(normalized["weight_g"])
        priced = suggest_price_for_package(
            supplier_price_cny=float(cost),
            depth_mm=int(normalized["depth_mm"]),
            width_mm=int(normalized["width_mm"]),
            height_mm=int(normalized["height_mm"]),
            weight_g=chargeable,
        )
        new_price = int(priced["pricing"]["list_price"])
        old_price = variant.get("price")
        try:
            old_price_n = float(old_price) if old_price is not None else None
        except (TypeError, ValueError):
            old_price_n = None
        row = {
            "sku": sku,
            "variant_id": variant.get("id"),
            "old_price": old_price_n,
            "new_price": new_price,
            "cost_cny": float(cost),
            "cost_match": (matched or {}).get("reason"),
            "matched_external_id": (matched or {}).get("matched_external_id"),
            "package_mm": [
                int(normalized["depth_mm"]),
                int(normalized["width_mm"]),
                int(normalized["height_mm"]),
            ],
            "actual_weight_g": int(normalized.get("actual_weight_g") or weight),
            "weight_g": chargeable,
            "channel": normalized["channel_name"],
            "freight_cny": normalized["freight_cny"],
            "weight_raised": bool(normalized.get("weight_raised")),
        }
        rows.append(row)
        pkg = (
            int(normalized["depth_mm"]),
            int(normalized["width_mm"]),
            int(normalized["height_mm"]),
            chargeable,
        )
        if max_pkg is None or pkg[3] > max_pkg[3]:
            max_pkg = pkg

        if dry_run:
            continue

        va = dict(variant.get("variant_attributes") or {})
        va = write_package_fields(
            va,
            depth_mm=pkg[0],
            width_mm=pkg[1],
            height_mm=pkg[2],
            weight_g=pkg[3],
        )
        va["freight_channel"] = normalized["channel_name"]
        va["freight_cny"] = str(normalized["freight_cny"])
        va["pricing_formula"] = priced["pricing"]["formula"]
        va["supplier_cost_cny"] = str(cost)
        if matched:
            va["cost_match_reason"] = str(matched.get("reason") or "")
            va["cost_match_external_id"] = str(matched.get("matched_external_id") or "")
        update_product_edit_variant(int(variant["id"]), price=float(new_price), variant_attributes=va)

    if not dry_run and max_pkg:
        attrs = write_package_fields(
            attrs,
            depth_mm=max_pkg[0],
            width_mm=max_pkg[1],
            height_mm=max_pkg[2],
            weight_g=max_pkg[3],
        )
        attrs["package_source"] = "xingyuan_size_first"
        # 用最重变体渠道作摘要
        heaviest = max(rows, key=lambda r: r["weight_g"])
        attrs["freight_channel"] = heaviest["channel"]
        attrs["freight_cny"] = str(heaviest["freight_cny"])
        attrs["pricing_formula"] = "per_variant_size_first"
        update_product_edit(edit_id, attributes=attrs, clear_listing=True)

    return {
        "edit_id": edit_id,
        "dry_run": dry_run,
        "variant_count": len(rows),
        "changed_prices": sum(
            1 for r in rows if r["old_price"] is None or int(round(r["old_price"])) != r["new_price"]
        ),
        "raised_weights": sum(1 for r in rows if r["weight_raised"]),
        "variants": rows,
    }


def push_edit_package_and_prices(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    items = build_import_items(edit)
    client = OzonSellerClient()

    # 锁定线上 category/type，避免改类目导致尺寸更新失败
    offer_ids = [str(it.get("offer_id") or "") for it in items if it.get("offer_id")]
    live_by_offer: dict[str, dict[str, Any]] = {}
    for i in range(0, len(offer_ids), 50):
        chunk = offer_ids[i : i + 50]
        try:
            data = client.request(
                "POST",
                "/v4/product/info/attributes",
                {
                    "filter": {"offer_id": chunk, "product_id": [], "sku": []},
                    "limit": 100,
                    "sort_dir": "ASC",
                },
            )
        except OzonSellerError as exc:
            logger.warning("拉取线上 attributes 失败 edit=%s: %s", edit_id, exc)
            continue
        for row in data.get("result") or []:
            oid = str(row.get("offer_id") or "")
            if oid:
                live_by_offer[oid] = row

    for item in items:
        live = live_by_offer.get(str(item.get("offer_id") or "")) or {}
        if live.get("type_id"):
            item["type_id"] = int(live["type_id"])
        if live.get("description_category_id"):
            item["description_category_id"] = int(live["description_category_id"])

    task_ids: list[Any] = []
    for i in range(0, len(items), 20):
        chunk = items[i : i + 20]
        resp = client.import_products(chunk)
        task_ids.append(extract_import_task_id(resp))
        time.sleep(1.2)

    # 再推一版价格，确保售价生效
    prices = []
    currency = str((edit.get("attributes") or {}).get("currency_code") or "CNY")
    for item in items:
        price = item.get("price")
        if not item.get("offer_id") or not price:
            continue
        prices.append(
            {
                "offer_id": item["offer_id"],
                "price": str(price),
                "old_price": str(item.get("old_price") or ""),
                "currency_code": currency,
            }
        )
    price_resp = []
    for i in range(0, len(prices), 100):
        price_resp.append(client.import_prices(prices[i : i + 100]))
        time.sleep(0.5)

    return {
        "edit_id": edit_id,
        "item_count": len(items),
        "import_task_ids": task_ids,
        "price_batches": len(price_resp),
    }


def repair_published_edits(
    *,
    edit_ids: list[int] | None = None,
    dry_run: bool = False,
    push: bool = True,
    limit: int = 200,
) -> dict[str, Any]:
    if edit_ids:
        targets = list(edit_ids)
    else:
        targets = [
            int(e["id"])
            for e in list_product_edits(limit=limit)
            if str(e.get("status") or "") in {"published", "approved"}
        ]

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for edit_id in targets:
        try:
            repaired = repair_edit_package_and_prices(edit_id, dry_run=dry_run)
            if push and not dry_run:
                repaired["push"] = push_edit_package_and_prices(edit_id)
            results.append(repaired)
            print(
                f"[pkg-price] edit {edit_id}: variants={repaired['variant_count']} "
                f"price_changed={repaired['changed_prices']} weight_raised={repaired['raised_weights']}",
                flush=True,
            )
        except Exception as exc:
            logger.exception("repair edit %s failed", edit_id)
            errors.append({"edit_id": edit_id, "error": str(exc)})
            print(f"[pkg-price] edit {edit_id} FAIL: {exc}", flush=True)

    return {
        "ok": not errors,
        "dry_run": dry_run,
        "push": push and not dry_run,
        "total": len(targets),
        "fixed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
