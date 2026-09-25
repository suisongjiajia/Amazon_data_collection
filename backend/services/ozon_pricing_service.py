from __future__ import annotations

import os
import re
from typing import Any

from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import list_supplier_candidates
from services.sourcing_service import _enrich_ozon_family_for_display
from services.xingyuan_freight import FreightError, calc_xingyuan_economy_freight_cny

# 理解 A：P = (G + F) × 1.30 / (1 - 0.30) = (G + F) × (1.30/0.70) ≈ (G + F) × 1.857
DEFAULT_COMMISSION_RATE = 0.30
DEFAULT_PROFIT_MARKUP = 1.30
DEFAULT_STOCK_QTY = 99


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_cny_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else None
    text = str(value)
    # 区间价取第一个有效数字（如 ¥5.50-¥8.80 → 5.50）
    match = re.search(r"(\d+(?:[.,]\d+)?)", text.replace(",", "."))
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return amount if amount > 0 else None


def parse_weight_grams(value: Any, attributes: dict[str, Any] | None = None) -> float | None:
    candidates: list[Any] = []
    if value is not None:
        candidates.append(value)
    for key, raw in (attributes or {}).items():
        lower = str(key).lower()
        if any(alias in lower for alias in ("вес", "weight", "重量", "масса")):
            candidates.append(raw)

    for item in candidates:
        if item is None:
            continue
        text = str(item).lower().replace(",", ".")
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            continue
        number = float(match.group(1))
        if "kg" in text or "кг" in text or "千克" in text:
            return number * 1000
        return number
    return None


def calc_suggested_price_rub(
    *,
    supplier_price_cny: float,
    freight_cny: float,
    commission_rate: float | None = None,
    profit_markup: float | None = None,
    rub_per_cny: float | None = None,
) -> dict[str, Any]:
    if supplier_price_cny <= 0:
        raise ValueError("供应商价格必须大于 0")
    if freight_cny < 0:
        raise ValueError("运费不能为负")

    commission = (
        _env_float("OZON_COMMISSION_RATE", DEFAULT_COMMISSION_RATE)
        if commission_rate is None
        else float(commission_rate)
    )
    markup = (
        _env_float("OZON_PROFIT_MARKUP", DEFAULT_PROFIT_MARKUP)
        if profit_markup is None
        else float(profit_markup)
    )
    fx = _env_float("OZON_RUB_PER_CNY", 12.0) if rub_per_cny is None else float(rub_per_cny)
    if commission >= 1:
        raise ValueError("佣金比例必须小于 1")
    if markup <= 0:
        raise ValueError("加价倍数必须大于 0")
    if fx <= 0:
        raise ValueError("汇率 OZON_RUB_PER_CNY 必须大于 0")

    cost_cny = supplier_price_cny + freight_cny
    # 理解 A：扣完佣金后，相对成本再赚 30%（默认佣金 30%）
    price_cny = cost_cny * markup / (1.0 - commission)
    price_rub = price_cny * fx
    price_cny_int = max(1, int(round(price_cny)))
    price_rub_int = max(1, int(round(price_rub)))
    currency_code = (os.getenv("OZON_CURRENCY_CODE") or "CNY").strip().upper() or "CNY"
    list_price = price_cny_int if currency_code == "CNY" else price_rub_int
    unit = "¥" if currency_code == "CNY" else "₽"

    return {
        "supplier_price_cny": round(supplier_price_cny, 2),
        "freight_cny": round(freight_cny, 2),
        "cost_cny": round(cost_cny, 2),
        "commission_rate": commission,
        "profit_markup": markup,
        "rub_per_cny": fx,
        "price_cny": round(price_cny, 2),
        "price_cny_int": price_cny_int,
        "price_rub": price_rub_int,
        "currency_code": currency_code,
        "list_price": list_price,
        "formula": (
            f"(({supplier_price_cny}+{freight_cny})×{markup}/(1-{commission}))"
            + (
                f" ≈ {list_price} {unit}"
                if currency_code == "CNY"
                else f"×{fx} ≈ {list_price} {unit}"
            )
        ),
        "stock_qty": _env_int("OZON_DEFAULT_STOCK_QTY", DEFAULT_STOCK_QTY),
    }


def scale_list_price(base_price: int, reference: float | None, anchor_reference: float | None) -> int:
    """按各规格在 Ozon 上的标价比例，把同一个成本价拉开。"""
    if base_price <= 0:
        return int(base_price)
    if reference is None or anchor_reference is None or anchor_reference <= 0 or reference <= 0:
        return int(base_price)
    return max(1, int(round(base_price * (reference / anchor_reference))))


def variant_prices_from_collected(
    base_price: int,
    variants: list[dict[str, Any]],
    *,
    anchor_external_id: str | None,
) -> list[int]:
    refs: list[float | None] = []
    anchor: float | None = None
    root_id = str(anchor_external_id or "").strip()
    for variant in variants:
        external_id = str(variant.get("external_id") or "").strip()
        if not external_id:
            sku = str(variant.get("sku") or "")
            if sku.startswith("OZON-"):
                external_id = sku[5:]
        ref = parse_cny_price(variant.get("price_text") or variant.get("collected_price_text"))
        refs.append(ref)
        if root_id and external_id == root_id and ref:
            anchor = ref
    if anchor is None:
        anchor = next((ref for ref in refs if ref), None)
    return [scale_list_price(base_price, ref, anchor) for ref in refs]


def _pick_supplier_price(candidates: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any] | None]:
    selected = [item for item in candidates if item.get("status") == "selected"]
    pool = selected or candidates[:1]
    if not pool:
        return None, None
    item = pool[0]
    price = parse_cny_price(item.get("price_text"))
    if price is None:
        raw = item.get("raw_payload") or {}
        price = parse_cny_price(raw.get("price"))
    return price, item


def suggest_price_for_family(raw_product_family_id: int) -> dict[str, Any]:
    family = get_ozon_product_family(raw_product_family_id)
    product = _enrich_ozon_family_for_display(family)
    candidates = list_supplier_candidates(raw_product_family_id, limit=20)
    supplier_price, supplier = _pick_supplier_price(candidates)
    if supplier_price is None and str(family.get("platform") or "") == "1688":
        # 1688 直采：用商品自身价格当货本
        raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
        supplier_price = parse_cny_price(raw.get("price_text"))
        if supplier_price is None:
            for variant in family.get("variants") or []:
                supplier_price = parse_cny_price(variant.get("price_text"))
                if supplier_price:
                    break
        supplier = {
            "id": None,
            "supplier_name": family.get("brand") or family.get("category_name"),
            "product_title": family.get("title"),
            "price_text": raw.get("price_text") or (family.get("variants") or [{}])[0].get("price_text"),
            "status": "self_1688",
        }
    if supplier_price is None:
        raise ValueError("缺少 1688 供应商价格，请先搜货并选定货源")

    attributes = dict(product.get("attributes") or {})
    # 1688：优先用详情包装表解析出的 package_metrics（取较重新，避免运费算少）
    if str(family.get("platform") or "") == "1688":
        raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
        nested = raw.get("raw") if isinstance(raw.get("raw"), dict) else {}
        metrics = nested.get("package_metrics") if isinstance(nested.get("package_metrics"), dict) else {}
        if not metrics and isinstance(raw.get("attributes"), dict):
            attributes = {**attributes, **raw["attributes"]}
        if metrics.get("weight_g"):
            try:
                weight_g = float(metrics["weight_g"])
                weight_assumed = False
            except (TypeError, ValueError):
                weight_g = None
                weight_assumed = True
        else:
            weight_g = parse_weight_grams(product.get("weight"), attributes)
            weight_assumed = weight_g is None
            if weight_g is None:
                weight_g = _env_float("OZON_DEFAULT_WEIGHT_G", 200.0)
    else:
        weight_g = parse_weight_grams(product.get("weight"), attributes)
        if weight_g is None:
            weight_g = _env_float("OZON_DEFAULT_WEIGHT_G", 200.0)
            weight_assumed = True
        else:
            weight_assumed = False

    try:
        freight_info = calc_xingyuan_economy_freight_cny(weight_g)
    except FreightError as exc:
        raise ValueError(str(exc)) from exc

    pricing = calc_suggested_price_rub(
        supplier_price_cny=supplier_price,
        freight_cny=float(freight_info["freight_cny"]),
    )

    return {
        "raw_product_family_id": raw_product_family_id,
        "supplier": {
            "id": supplier.get("id") if supplier else None,
            "supplier_name": supplier.get("supplier_name") if supplier else None,
            "product_title": supplier.get("product_title") if supplier else None,
            "price_text": supplier.get("price_text") if supplier else None,
            "status": supplier.get("status") if supplier else None,
        },
        "weight_g": freight_info["weight_g"],
        "weight_assumed": weight_assumed,
        "freight": freight_info,
        "pricing": pricing,
        "listing_notes": (
            f"定价理解A：((货本{pricing['supplier_price_cny']}+运费{pricing['freight_cny']})"
            f"×{pricing['profit_markup']})/(1-{pricing['commission_rate']})"
            + (
                ""
                if pricing["currency_code"] == "CNY"
                else f"×汇率{pricing['rub_per_cny']}"
            )
            + f" → {pricing['list_price']} {pricing['currency_code']}；"
            f"渠道 {freight_info['channel_name']}；库存默认 {pricing['stock_qty']}"
            + ("；重量为默认估算，请核对" if weight_assumed else "")
        ),
    }
