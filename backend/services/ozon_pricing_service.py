from __future__ import annotations

import os
import re
from typing import Any

from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import list_supplier_candidates
from services.sourcing_service import _enrich_ozon_family_for_display
from services.xingyuan_freight import FreightError, calc_xingyuan_economy_freight_cny

# 理解 A：P = (G + F) × 1.30 / (1 - 0.20) = (G + F) × 1.625
DEFAULT_COMMISSION_RATE = 0.20
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
    digits = re.sub(r"[^\d.,]", "", text).replace(",", ".")
    if not digits:
        return None
    try:
        amount = float(digits)
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

    commission = DEFAULT_COMMISSION_RATE if commission_rate is None else float(commission_rate)
    markup = DEFAULT_PROFIT_MARKUP if profit_markup is None else float(profit_markup)
    fx = _env_float("OZON_RUB_PER_CNY", 12.0) if rub_per_cny is None else float(rub_per_cny)
    if commission >= 1:
        raise ValueError("佣金比例必须小于 1")
    if markup <= 0:
        raise ValueError("加价倍数必须大于 0")
    if fx <= 0:
        raise ValueError("汇率 OZON_RUB_PER_CNY 必须大于 0")

    cost_cny = supplier_price_cny + freight_cny
    # 理解 A：扣完 20% 佣金后，相对成本再赚 30%
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
    if supplier_price is None:
        raise ValueError("缺少 1688 供应商价格，请先搜货并选定货源")

    attributes = product.get("attributes") or {}
    weight_g = parse_weight_grams(product.get("weight"), attributes)
    if weight_g is None:
        # 无重量时按 Extra Small 上限估算，避免无法定价；明细里会标明
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
