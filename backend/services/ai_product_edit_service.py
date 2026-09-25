from __future__ import annotations

import json
import re
from typing import Any

from db.ozon_catalog import get_ozon_product_family
from db.ozon_workflow import list_supplier_candidates
from integrations.deepseek.client import DeepSeekClient, DeepSeekError
from services.sourcing_service import _enrich_ozon_family_for_display

SYSTEM_PROMPT = """你是 Ozon 跨境电商 listing 专家。根据采集到的商品信息（可能来自 Ozon 对标品或 1688 货源）、规格、类目属性清单，生成可直接用于 Ozon Seller API 上架的俄语商品内容。

要求：
1. 标题、描述、卖点 bullet_points 使用俄语，符合 Ozon 规范，标题简洁有卖点（不超过 200 字符）。
2. description 为纯文本，可包含换行，不要 HTML；建议 600～1500 字符，覆盖用途、材质、尺寸、场景、保养。
3. bullet_points 5-8 条，突出材质、适用对象、功能、尺寸、包装等。
4. attributes 必须尽量填满 context.ozon_fillable_attributes 中的每一项：
   - 键名必须与清单中的俄语属性名完全一致（不要用中文键名）
   - 值为俄语或数字字符串；字典枚举类属性填常见俄语选项（如 Страна-изготовитель=Китай，Нужен код маркировки=Нет）
   - 重量相关用克（例如 Вес товара, г=500）；包装尺寸用厘米字符串如 36x36x36
   - 件数/数量类默认 1；#Хештеги 用空格分隔的俄语标签
   - Аннотация 用完整俄语描述（用途、材质、尺寸、场景、保养），不要只写一两句
   - Комплектация 按行写清每件包含物和数量，例如「Домик — 1 шт.」
   - 无法合理推断的属性可省略，不要编造危险/违法信息
5. search_keywords 为俄语搜索词数组（8～15 个）。
6. category_hint 为建议的 Ozon 类目路径（俄语或中文均可）。
7. variants 数组：每个变体含 title（俄语，可带尺寸/颜色区分）。不要自行编造 price / quantity。
8. listing_notes 用中文简要说明文案注意点（不要写定价公式）。

只输出 JSON 对象，不要 markdown，字段：
{
  "title": "string",
  "description": "string",
  "bullet_points": ["string"],
  "attributes": {"俄语属性名": "string"},
  "search_keywords": ["string"],
  "category_hint": "string",
  "variants": [{"title": "string"}],
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
    is_1688 = str(family.get("platform") or "") == "1688"
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
    if is_1688 and not suppliers:
        raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
        suppliers.append(
            {
                "supplier_name": family.get("brand") or family.get("category_name"),
                "product_title": family.get("title"),
                "price_text": raw.get("price_text"),
                "status": "self_1688",
            }
        )

    fillable_attributes = _load_fillable_attribute_names(
        product.get("description_category_id") or family.get("category_id"),
        product.get("type_id") or family.get("type_id"),
    )

    source_images = list(product.get("images") or [])
    if isinstance(family.get("raw_payload"), dict):
        for url in (family.get("raw_payload") or {}).get("images") or []:
            if isinstance(url, str) and url.startswith("http") and url not in source_images:
                source_images.append(url)
    if isinstance(family.get("bullet_points"), list):
        for url in family.get("bullet_points") or []:
            if isinstance(url, str) and url.startswith("http") and url not in source_images:
                source_images.append(url)
    if not source_images and family.get("main_image_url"):
        source_images = [family.get("main_image_url")]

    return {
        "source_platform": "1688" if is_1688 else "ozon",
        "ozon_product": {
            "external_id": product.get("external_id"),
            "title": product.get("title"),
            "brand": product.get("brand"),
            "category_name": product.get("category_name"),
            "price_text": product.get("price_text")
            or (family.get("raw_payload") or {}).get("price_text")
            if isinstance(family.get("raw_payload"), dict)
            else product.get("price_text"),
            "description": product.get("description"),
            "size": product.get("size"),
            "weight": product.get("weight"),
            "attributes": product.get("attributes")
            or (
                (family.get("raw_payload") or {}).get("attributes")
                if isinstance(family.get("raw_payload"), dict)
                else {}
            )
            or {},
            "images": source_images,
            "main_image_url": product.get("main_image_url") or family.get("main_image_url"),
            "description_category_id": product.get("description_category_id") or family.get("category_id"),
            "type_id": product.get("type_id") or family.get("type_id"),
            "rating": product.get("rating"),
            "review_count": product.get("review_count"),
            "source_url": product.get("source_url") or family.get("source_url"),
            "variants": [
                {
                    "external_id": v.get("external_id"),
                    "title": v.get("title"),
                    "variant_attributes": v.get("variant_attributes") or {},
                    "price_text": v.get("price_text"),
                }
                for v in (product.get("variants") or family.get("variants") or [])[:12]
            ],
        },
        "ozon_fillable_attributes": fillable_attributes,
        "suppliers_1688": suppliers,
    }


def _load_fillable_attribute_names(category_id: Any, type_id: Any) -> list[str]:
    try:
        cat = int(str(category_id))
        typ = int(str(type_id))
    except (TypeError, ValueError):
        return []
    try:
        from services.ozon_attribute_fill import fetch_category_attributes

        schema = fetch_category_attributes(cat, typ)
    except Exception:
        return []
    names: list[str] = []
    for attr in schema:
        name = str(attr.get("name") or attr.get("description") or "").strip()
        if not name:
            continue
        lower = name.lower()
        if lower in {"бренд", "brand"}:
            continue
        names.append(name)
    return names[:80]


def _normalize_ai_result(raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from services.ozon_pricing_service import DEFAULT_STOCK_QTY

    ozon = context.get("ozon_product") or {}
    external_id = ozon.get("external_id") or "sku"
    source_platform = str(context.get("source_platform") or "ozon")
    default_sku = f"A1688-{external_id}" if source_platform == "1688" else f"OZON-{external_id}"
    default_qty = DEFAULT_STOCK_QTY

    variants_raw = raw.get("variants")
    variants: list[dict[str, Any]] = []
    if isinstance(variants_raw, list) and variants_raw:
        for index, item in enumerate(variants_raw):
            if not isinstance(item, dict):
                continue
            variants.append(
                {
                    "sku": str(item.get("sku") or default_sku if index == 0 else f"{default_sku}-{index + 1}"),
                    "title": str(item.get("title") or raw.get("title") or ozon.get("title") or ""),
                    "price": None,
                    "quantity": default_qty,
                }
            )
    else:
        variants.append(
            {
                "sku": default_sku,
                "title": str(raw.get("title") or ozon.get("title") or ""),
                "price": None,
                "quantity": default_qty,
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

    # 保留采集到的上架 ID，不被 AI 覆盖
    for key in ("description_category_id", "type_id", "size", "weight"):
        value = ozon.get(key)
        if value and key not in attributes:
            attributes[key] = str(value)
    attributes.setdefault("brand_mode", "no_brand")
    attributes.setdefault("fulfillment", "rFBS")

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


def _apply_pricing_and_images(
    raw_product_family_id: int,
    suggestion: dict[str, Any],
    *,
    rehost_images: bool = True,
) -> dict[str, Any]:
    from services.ozon_pricing_service import suggest_price_for_family
    from integrations.aliyun_oss import rehost_image_urls
    from integrations.aliyun_oss.client import OssError

    pricing_result: dict[str, Any] | None = None
    try:
        pricing_result = suggest_price_for_family(raw_product_family_id)
        list_price = pricing_result["pricing"]["list_price"]
        stock_qty = pricing_result["pricing"]["stock_qty"]
        for variant in suggestion.get("variants") or []:
            variant["price"] = list_price
            variant["quantity"] = stock_qty
        note = pricing_result.get("listing_notes") or ""
        old = suggestion.get("listing_notes") or ""
        suggestion["listing_notes"] = f"{note}\n{old}".strip()
        suggestion.setdefault("attributes", {})
        suggestion["attributes"]["pricing_formula"] = pricing_result["pricing"]["formula"]
        suggestion["attributes"]["currency_code"] = pricing_result["pricing"]["currency_code"]
        suggestion["attributes"]["freight_channel"] = pricing_result["freight"]["channel_name"]
        suggestion["attributes"]["freight_cny"] = str(pricing_result["freight"]["freight_cny"])
    except Exception as exc:
        suggestion.setdefault("attributes", {})
        suggestion["attributes"]["pricing_error"] = str(exc)
        for variant in suggestion.get("variants") or []:
            if variant.get("quantity") in {None, 0, 10}:
                from services.ozon_pricing_service import DEFAULT_STOCK_QTY

                variant["quantity"] = DEFAULT_STOCK_QTY

    image_result: dict[str, Any] | None = None
    if rehost_images and suggestion.get("images"):
        original_images = list(suggestion.get("images") or [])
        try:
            sku = (suggestion.get("variants") or [{}])[0].get("sku") or f"family-{raw_product_family_id}"
            image_result = rehost_image_urls(list(suggestion["images"]), sku=str(sku))
            hosted = list(image_result.get("images") or [])
            # 转存后若图变少，用原图补齐，避免 listing 因图不够卡死
            if len(hosted) < 5 and len(original_images) > len(hosted):
                for url in original_images:
                    if url not in hosted:
                        hosted.append(url)
                    if len(hosted) >= 10:
                        break
            suggestion["images"] = hosted
            # 每个变体独立 listing：写入各自主图+副图（主图优先）
            for variant in suggestion.get("variants") or []:
                primary = str(variant.get("image_url") or variant.get("main_image_url") or "").strip()
                own: list[str] = []
                if primary:
                    own.append(primary)
                for url in hosted:
                    if url not in own:
                        own.append(url)
                va = dict(variant.get("variant_attributes") or {})
                va["images"] = own[:15]
                if own:
                    va["image_url"] = own[0]
                    variant["image_url"] = own[0]
                variant["variant_attributes"] = va
        except OssError as exc:
            suggestion.setdefault("attributes", {})
            suggestion["attributes"]["image_rehost_error"] = str(exc)
        except Exception as exc:
            suggestion.setdefault("attributes", {})
            suggestion["attributes"]["image_rehost_error"] = str(exc)

    return {
        "suggestion": suggestion,
        "pricing": pricing_result,
        "image_rehost": image_result,
    }


def generate_product_edit(raw_product_family_id: int, *, rehost_images: bool = True) -> dict[str, Any]:
    context = _build_ai_context(raw_product_family_id)
    user_prompt = (
        "请根据以下 JSON 数据生成 Ozon 上架文案（标题/描述/卖点/规格）。"
        "不要编造售价与库存。若 1688 货源为空，仅依据 Ozon 采集信息生成。\n\n"
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

    applied = _apply_pricing_and_images(
        raw_product_family_id,
        result,
        rehost_images=rehost_images,
    )
    return {
        "context": context,
        "suggestion": applied["suggestion"],
        "pricing": applied["pricing"],
        "image_rehost": applied["image_rehost"],
    }
