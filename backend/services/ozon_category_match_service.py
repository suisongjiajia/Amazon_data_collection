from __future__ import annotations

import json
import logging
from typing import Any

from db.ozon_catalog import get_ozon_product_family
from services.ozon_category_tree import correct_category_id_for_type, search_types_by_query

logger = logging.getLogger(__name__)


def _update_family_ids(family_id: int, *, description_category_id: str, type_id: str) -> None:
    from services.ozon_category_resolve_service import update_family_category_ids

    update_family_category_ids(
        family_id,
        description_category_id=description_category_id,
        type_id=type_id,
    )


def _ai_pick_type(title: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    if len(candidates) == 1 or int(candidates[0].get("score") or 0) >= int(candidates[1].get("score") or 0) + 20:
        return candidates[0]
    try:
        from integrations.deepseek.client import DeepSeekClient

        prompt = {
            "title": title,
            "candidates": [
                {
                    "type_id": item.get("type_id"),
                    "type_name": item.get("type_name"),
                    "score": item.get("score"),
                }
                for item in candidates[:8]
            ],
        }
        raw = DeepSeekClient().chat_json(
            system_prompt=(
                "你是 Ozon 类目专家。根据中文/俄语商品标题，从候选 type 里选最合适的一个。"
                "只输出 JSON：{\"type_id\": number, \"reason\": \"中文一句话\"}"
            ),
            user_prompt=json.dumps(prompt, ensure_ascii=False),
        )
        picked_id = int(str(raw.get("type_id") or "").strip())
        for item in candidates:
            if int(item.get("type_id") or 0) == picked_id:
                item = dict(item)
                item["ai_reason"] = str(raw.get("reason") or "")
                item["source"] = "ai_pick"
                return item
    except Exception as exc:
        logger.warning("AI 类目挑选失败，回退最高分: %s", exc)
    top = dict(candidates[0])
    top["source"] = "top_score"
    return top


def _ai_search_queries(title: str) -> list[str]:
    """中文标题 → 俄语检索词（Ozon type_name 多为俄语）。"""
    text = str(title or "").strip()
    if not text:
        return []
    try:
        from integrations.deepseek.client import DeepSeekClient

        raw = DeepSeekClient().chat_json(
            system_prompt=(
                "你是 Ozon 类目检索助手。根据商品标题输出 1~3 个俄语检索词，"
                "用于在 Ozon type_name 里搜索。只输出 JSON："
                '{"queries":["лестница для животных","..."]}'
            ),
            user_prompt=text[:300],
        )
        queries = raw.get("queries") if isinstance(raw, dict) else None
        if not isinstance(queries, list):
            return []
        out: list[str] = []
        for item in queries:
            q = str(item or "").strip()
            if q and q not in out:
                out.append(q)
        return out[:3]
    except Exception as exc:
        logger.warning("AI 类目检索词失败: %s", exc)
        return []


def match_category_for_family(family_id: int, *, force: bool = False) -> dict[str, Any]:
    """
    为 1688（或无类目）商品按标题匹配 Ozon description_category_id + type_id。
    """
    family = get_ozon_product_family(family_id)
    existing_cat = str(family.get("category_id") or "").strip()
    existing_type = str(family.get("type_id") or "").strip()
    if not force and existing_cat.isdigit() and existing_type.isdigit():
        return {
            "family_id": family_id,
            "description_category_id": existing_cat,
            "type_id": existing_type,
            "type_name": None,
            "source": "cached",
            "candidates": [],
        }

    title = str(family.get("title") or "").strip()
    raw = family.get("raw_payload") if isinstance(family.get("raw_payload"), dict) else {}
    attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
    hint = " ".join(
        str(x)
        for x in (
            title,
            family.get("category_name"),
            attrs.get("类型"),
            attrs.get("类目"),
            attrs.get("材质"),
        )
        if x
    )
    candidates = search_types_by_query(hint or title, limit=12)
    # 中文标题在俄语类目树上常无命中：用 AI 产出俄语检索词再搜
    if not candidates:
        for query in _ai_search_queries(title):
            candidates = search_types_by_query(query, limit=12)
            if candidates:
                break
    if not candidates:
        raise ValueError(f"未能根据标题匹配到 Ozon 类目：{title or family_id}")

    picked = _ai_pick_type(title, candidates) or candidates[0]
    type_id = str(picked.get("type_id") or "").strip()
    category_id = str(picked.get("description_category_id") or "").strip()
    category_id, type_id, _changed = correct_category_id_for_type(
        description_category_id=category_id,
        type_id=type_id,
    )
    if not category_id or not type_id:
        raise ValueError(f"类目匹配结果无效：{picked}")

    _update_family_ids(
        family_id,
        description_category_id=str(category_id),
        type_id=str(type_id),
    )
    return {
        "family_id": family_id,
        "description_category_id": str(category_id),
        "type_id": str(type_id),
        "type_name": picked.get("type_name"),
        "score": picked.get("score"),
        "source": picked.get("source") or "search",
        "ai_reason": picked.get("ai_reason"),
        "candidates": candidates[:8],
    }
