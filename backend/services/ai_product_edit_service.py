from __future__ import annotations

import json
import re
from typing import Any

from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import list_supplier_candidates
from integrations.deepseek.client import DeepSeekClient, DeepSeekError
from services.sourcing_service import _enrich_ozon_family_for_display

SYSTEM_PROMPT = """你是 Ozon 跨境电商 listing 专家。根据采集到的 Ozon 商品信息、规格和 1688 货源，生成可直接用于 Ozon Seller API 上架的俄语商品内容。

要求：
1. 标题、描述、卖点 bullet_points 使用俄语，符合 Ozon 规范，标题简洁有卖点（不超过 200 字符）。
2. description 为纯文本，可包含换行，不要 HTML。
3. bullet_points 3-7 条，突出材质、兼容性、包装数量等。
4. attributes 保留并补充关键规格（类型、型号、尺寸、重量、材质、品牌等），键名用俄语或通用英文。
5. search_keywords 为俄语搜索词数组。
6. category_hint 为建议的 Ozon 类目路径（俄语或中文均可）。
7. variants 数组：每个变体含 title（俄语）、price（卢布整数，参考原价与货源成本合理定价）、quantity（建议库存，默认 10）。
8. listing_notes 用中文简要说明定价思路与注意事项。

只输出 JSON 对象，不要 markdown，字段：
{
  "title": "string",
  "description": "string",
  "bullet_points": ["string"],
  "attributes": {"string": "string"},
  "search_keywords": ["string"],
  "category_hint": "string",
  "variants": [{"title": "string", "price": number, "quantity": number}],
  "listing_notes": "string"
}"""


def _parse_price_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    digits = re.sub(r"[^\d.,]", "", text).replace(",", ".")
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _build_ai_context(raw_product_family_id: int) -> dict[str, Any]:
    family = get_ozon_product_family(raw_product_family_id)
    product = _enrich_ozon_family_for_display(family)
    candidates = list_supplier_candidates(raw_product_family_id, limit=20)
    selected = [item for item in candidates if item.get("status") == "selected"]
    supplier_pool = selected or candidates[:3]

    suppliers = []
    for item in supplier_pool:
        suppliers.append(
            {
                "supplier_name": item.get("supplier_name"),
                "product_title": item.get("product_title"),
                "price_text": item.get("price_text"),
                "min_order_qty": item.get("min_order_qty"),
                "match_score": item.get("match_score"),
                "status": item.get("status"),
            }
        )

    return {
        "ozon_product": {
            "external_id": product.get("external_id"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "category_name": product.get("category_name"),
            "price_text": product.get("price_text"),
            "description": product.get("description"),
            "size": product.get("size"),
            "weight": product.get("weight"),
            "attributes": product.get("attributes") or {},
            "images": product.get("images") or [],
            "main_image_url": product.get("main_image_url"),
            "rating": product.get("rating"),
            "review_count": product.get("review_count"),
            "source_url": product.get("source_url"),
        },
        "suppliers_1688": suppliers,
    }


def _normalize_ai_result(raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    ozon = context.get("ozon_product") or {}
    external_id = ozon.get("external_id") or "sku"
    default_sku = f"OZON-{external_id}"

    variants_raw = raw.get("variants")
    variants: list[dict[str, Any]] = []
    if isinstance(variants_raw, list) and variants_raw:
        for index, item in enumerate(variants_raw):
            if not isinstance(item, dict):
                continue
            price = _parse_price_number(item.get("price")) or _parse_price_number(ozon.get("price_text"))
            quantity = item.get("quantity")
            try:
                quantity = int(quantity)
            except (TypeError, ValueError):
                quantity = 10
            variants.append(
                {
                    "sku": str(item.get("sku") or default_sku if index == 0 else f"{default_sku}-{index + 1}"),
                    "title": str(item.get("title") or raw.get("title") or ozon.get("title") or ""),
                    "price": price,
                    "quantity": max(0, quantity),
                }
            )
    else:
        variants.append(
            {
                "sku": default_sku,
                "title": str(raw.get("title") or ozon.get("title") or ""),
                "price": _parse_price_number(ozon.get("price_text")),
                "quantity": 10,
            }
        )

    bullet_points = raw.get("bullet_points")
    if not isinstance(bullet_points, list):
        bullet_points = []
    bullet_points = [str(item).strip() for item in bullet_points if str(item).strip()]

    attributes = raw.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    attributes = {str(k): str(v) for k, v in attributes.items() if v is not None and str(v).strip()}

    search_keywords = raw.get("search_keywords")
    if isinstance(search_keywords, list) and search_keywords:
        attributes["search_keywords"] = ", ".join(str(k).strip() for k in search_keywords if str(k).strip())
    if raw.get("category_hint"):
        attributes["category_hint"] = str(raw["category_hint"]).strip()

    images = ozon.get("images") or []
    if ozon.get("main_image_url"):
        main = ozon["main_image_url"]
        if main not in images:
            images = [main, *images]

    return {
        "title": str(raw.get("title") or ozon.get("title") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "bullet_points": bullet_points,
        "images": images[:10],
        "attributes": attributes,
        "variants": variants,
        "listing_notes": str(raw.get("listing_notes") or "").strip(),
    }


def generate_product_edit(raw_product_family_id: int) -> dict[str, Any]:
    context = _build_ai_context(raw_product_family_id)
    user_prompt = (
        "请根据以下 JSON 数据生成 Ozon 上架内容。"
        "若 1688 货源为空，仅依据 Ozon 采集信息生成。\n\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )

    client = DeepSeekClient()
    try:
        raw = client.chat_json(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
    except DeepSeekError:
        raise
    except Exception as exc:
        raise DeepSeekError(str(exc)) from exc

    result = _normalize_ai_result(raw, context)
    if not result["title"]:
        raise DeepSeekError("AI 未生成有效标题")
    return {"context": context, "suggestion": result}
