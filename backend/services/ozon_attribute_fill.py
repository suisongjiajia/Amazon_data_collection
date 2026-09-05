from __future__ import annotations

import os
import re
from typing import Any

from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _as_int(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_attribute_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        attrs = result.get("attributes") or result.get("result")
        if isinstance(attrs, list):
            return [item for item in attrs if isinstance(item, dict)]
    attrs = payload.get("attributes")
    if isinstance(attrs, list):
        return [item for item in attrs if isinstance(item, dict)]
    return []


def _parse_value_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        values = result.get("values") or result.get("result")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return []


def fetch_category_attributes(description_category_id: int, type_id: int) -> list[dict[str, Any]]:
    client = OzonSellerClient()
    last_error: Exception | None = None
    for language in ("DEFAULT", "RU"):
        try:
            payload = client.get_description_category_attributes(
                description_category_id=description_category_id,
                type_id=type_id,
                language=language,
            )
            attrs = _parse_attribute_list(payload)
            if attrs:
                return attrs
            last_error = OzonSellerError(
                f"类目属性为空（description_category_id={description_category_id}, type_id={type_id}, language={language}）"
            )
        except OzonSellerError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return []


def _tokenize_tokens(*texts: Any) -> list[str]:
    """从标题/类目提示拆出可用于字典搜索的词（优先较长俄文/拉丁片段）。"""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in texts:
        text = str(raw or "").strip()
        if not text:
            continue
        # 整句前缀
        for chunk in (text[:40], text):
            cleaned = re.sub(r"\s+", " ", chunk).strip(" .,;:/|-")
            if len(cleaned) >= 2 and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                tokens.append(cleaned)
        parts = re.findall(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-]{1,}", text)
        for part in parts:
            low = part.lower()
            if low in seen or len(part) < 2:
                continue
            seen.add(low)
            tokens.append(part)
    # 长词优先，更易命中类型名
    tokens.sort(key=lambda t: (-len(t), t.lower()))
    return tokens[:12]


def _score_dict_candidate(query: str, candidate_value: str) -> int:
    q = _norm(query)
    v = _norm(candidate_value)
    if not q or not v:
        return 0
    if q == v:
        return 1000
    if q in v or v in q:
        return 800 + min(len(q), len(v))
    # 简单字符重叠
    overlap = len(set(q) & set(v))
    return overlap * 3


def pick_dictionary_value(
    *,
    client: OzonSellerClient,
    attribute_id: int,
    description_category_id: int,
    type_id: int,
    queries: list[str],
) -> dict[str, Any] | None:
    """
    自动挑选字典枚举：
    1) search 优先（含类型名），命中 id==type_id 立即采用
    2) 枚举首页 id == type_id
    3) 首页枚举用查询词打分
    """
    best: dict[str, Any] | None = None
    best_score = 0

    def consider(item: dict[str, Any], query: str, base: int = 0) -> None:
        nonlocal best, best_score
        vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
        label = str(item.get("value") or "").strip()
        if vid is None or not label:
            return
        score = base + _score_dict_candidate(query, label)
        if vid == type_id:
            score = max(score, 2000)
        if score > best_score:
            best_score = score
            best = {
                "dictionary_value_id": vid,
                "value": label,
                "source": "search" if base else "values_scan",
            }

    # 1) search（限制次数，避免拖慢生成 Listing）
    for query in queries[:6]:
        q = str(query or "").strip()
        if len(q) < 2:
            continue
        try:
            payload = client.search_attribute_values(
                attribute_id=attribute_id,
                description_category_id=description_category_id,
                type_id=type_id,
                value=q[:80],
                limit=20,
            )
        except OzonSellerError:
            continue
        for item in _parse_value_list(payload):
            consider(item, q, base=50)
            vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
            if vid == type_id:
                return {
                    "dictionary_value_id": vid,
                    "value": str(item.get("value") or ""),
                    "source": "search_type_id",
                }
        if best_score >= 800:
            return best

    # 2/3) 首页 values
    try:
        page = client.get_attribute_values(
            attribute_id=attribute_id,
            description_category_id=description_category_id,
            type_id=type_id,
            limit=100,
            last_value_id=0,
        )
        values = _parse_value_list(page)
    except OzonSellerError:
        values = []

    for item in values:
        vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
        if vid == type_id:
            return {
                "dictionary_value_id": vid,
                "value": str(item.get("value") or ""),
                "source": "type_id_match",
            }

    for query in queries[:4]:
        for item in values:
            consider(item, query, base=0)

    if best and best_score >= 20:
        return best
    return None


def _default_model_name(*, edit_title: str, edit_attributes: dict[str, Any], variants: list[dict[str, Any]]) -> str:
    explicit = (
        edit_attributes.get("model")
        or edit_attributes.get("модель")
        or edit_attributes.get("型号")
        or edit_attributes.get("Название модели")
    )
    if explicit and str(explicit).strip():
        return str(explicit).strip()[:80]

    sku = ""
    for variant in variants or []:
        sku = str(variant.get("sku") or "").strip()
        if sku:
            break
    title = str(edit_title or "").strip()
    if title:
        # 取标题前段作型号，去掉过长尾巴
        short = re.split(r"[|/]", title, maxsplit=1)[0].strip()
        short = re.sub(r"\s+", " ", short)[:60]
        if short:
            return short
    if sku:
        return sku[:50]
    return "Model-1"


def _find_source_value(attr_name: str, source_map: dict[str, str]) -> str | None:
    target = _norm(attr_name)
    if not target:
        return None
    if target in source_map:
        return source_map[target]
    for key, value in source_map.items():
        if not value:
            continue
        if target in key or key in target:
            return value
    aliases = {
        "бренд": ["brand", "品牌", "бренд"],
        "модель": ["model", "型号", "модель", "названиемодели"],
        "цвет": ["color", "цвет", "颜色"],
        "материал": ["material", "материал", "材质"],
        "тип": ["type", "тип", "类型"],
    }
    for canonical, keys in aliases.items():
        if any(k in target for k in keys) or canonical in target:
            for key, value in source_map.items():
                if any(k in key for k in keys) and value:
                    return value
    return None


def _build_source_map(edit_attributes: dict[str, Any]) -> dict[str, str]:
    source: dict[str, str] = {}
    skip_keys = {
        "description_category_id",
        "type_id",
        "category_id",
        "brand_mode",
        "fulfillment",
        "pricing_formula",
        "freight_channel",
        "freight_cny",
        "pricing_error",
        "category_resolve_error",
        "missing_required_attributes",
        "image_rehost_error",
        "search_keywords",
        "currency_code",
        "ozon_auto_attributes",
    }
    for key, value in (edit_attributes or {}).items():
        if key in skip_keys or value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        source[_norm(key)] = text
    return source


def format_missing_attribute_labels(items: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for item in items:
        text = str(item.get("message") or item.get("name") or "").strip()
        if text:
            labels.append(text)
    return "; ".join(labels[:12])


def build_ozon_attribute_values(
    *,
    description_category_id: int,
    type_id: int,
    edit_attributes: dict[str, Any],
    edit_title: str = "",
    variants: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    返回 (可提交 attributes[], warnings[])
    会尽量自动选择字典枚举与型号文本。
    """
    from services.ozon_category_tree import find_category_id_for_type, find_type_name

    category_id = description_category_id
    try:
        schema = fetch_category_attributes(category_id, type_id)
    except OzonSellerError as first_exc:
        corrected = find_category_id_for_type(type_id)
        if corrected and corrected != category_id:
            try:
                schema = fetch_category_attributes(corrected, type_id)
                category_id = corrected
                edit_attributes["description_category_id"] = str(corrected)
            except OzonSellerError as second_exc:
                return [], [
                    {
                        "id": None,
                        "code": "ATTRIBUTE_SCHEMA_FETCH_FAILED",
                        "name": "类目属性接口",
                        "message": f"拉取类目属性失败: {second_exc}",
                    }
                ]
        else:
            return [], [
                {
                    "id": None,
                    "code": "ATTRIBUTE_SCHEMA_FETCH_FAILED",
                    "name": "类目属性接口",
                    "message": f"拉取类目属性失败: {first_exc}",
                }
            ]

    brand_attr_id = _as_int(os.getenv("OZON_BRAND_ATTRIBUTE_ID", "85")) or 85
    no_brand_dict_id = _as_int(os.getenv("OZON_NO_BRAND_DICTIONARY_VALUE_ID", "126745801"))
    source_map = _build_source_map(edit_attributes)
    variants = variants or []

    type_name = find_type_name(type_id) or str(edit_attributes.get("type_name") or "")
    search_queries = _tokenize_tokens(
        type_name,
        edit_title,
        edit_attributes.get("category_hint"),
        *[str(v.get("title") or "") for v in variants[:3]],
    )

    client = OzonSellerClient()
    auto_notes: list[str] = []

    filled: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    filled.append(
        {
            "id": brand_attr_id,
            "values": (
                [{"dictionary_value_id": no_brand_dict_id}]
                if no_brand_dict_id
                else [{"value": "Нет бренда"}]
            ),
        }
    )
    seen_ids.add(brand_attr_id)

    for attr in schema:
        attr_id = _as_int(attr.get("id") or attr.get("attribute_id"))
        if attr_id is None or attr_id in seen_ids:
            continue
        name = str(attr.get("name") or attr.get("description") or f"attr-{attr_id}")
        is_required = bool(attr.get("is_required") or attr.get("required"))
        if attr_id == brand_attr_id or _norm(name) in {"бренд", "brand", "品牌"}:
            continue

        dictionary_id = attr.get("dictionary_id")
        has_dictionary = bool(_as_int(dictionary_id))
        source_value = _find_source_value(name, source_map)
        name_norm = _norm(name)
        is_model_attr = any(k in name_norm for k in ("модел", "model", "型号", "названиемодели"))

        # 非必填且无来源：跳过，不打字典搜索
        if not is_required and not source_value and not is_model_attr:
            continue

        if not has_dictionary:
            value = source_value
            if not value and is_model_attr:
                value = _default_model_name(
                    edit_title=edit_title,
                    edit_attributes=edit_attributes,
                    variants=variants,
                )
                auto_notes.append(f"{name}={value}")
            if value:
                filled.append({"id": attr_id, "values": [{"value": value}]})
                seen_ids.add(attr_id)
                continue
            if is_required:
                missing.append(
                    {
                        "id": attr_id,
                        "code": "MISSING_REQUIRED_ATTRIBUTE",
                        "name": name,
                        "dictionary_id": dictionary_id,
                        "message": name,
                    }
                )
            continue

        # 字典属性：自动搜索/匹配枚举
        queries = list(search_queries)
        if source_value:
            queries.insert(0, source_value)

        picked = pick_dictionary_value(
            client=client,
            attribute_id=attr_id,
            description_category_id=category_id,
            type_id=type_id,
            queries=queries,
        )
        if picked:
            filled.append(
                {
                    "id": attr_id,
                    "values": [{"dictionary_value_id": picked["dictionary_value_id"]}],
                }
            )
            seen_ids.add(attr_id)
            auto_notes.append(f"{name}={picked.get('value') or picked['dictionary_value_id']}")
            continue

        if is_required:
            missing.append(
                {
                    "id": attr_id,
                    "code": "MISSING_REQUIRED_ATTRIBUTE",
                    "name": name,
                    "dictionary_id": dictionary_id,
                    "message": f"{name}（字典属性，自动匹配失败）",
                }
            )

    if auto_notes:
        edit_attributes["ozon_auto_attributes"] = "; ".join(auto_notes[:12])

    return filled, missing
