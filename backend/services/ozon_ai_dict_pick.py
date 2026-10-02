"""
Ozon 字典属性：API 拉候选 →（必要时）AI 从白名单中选 → 代码校验。

速度策略：
- 并行拉候选（ThreadPoolExecutor）
- 高分匹配直接采用，不调 AI
- Тип 只用 type_id，永不走 AI
- 其余歧义项合并成 **一次** DeepSeek JSON 调用
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError
from services.ozon_attribute_fill import (
    _as_int,
    _is_type_attr_name,
    _norm,
    _parse_value_list,
    _score_dict_candidate,
)


AI_DICT_SYSTEM_PROMPT = """你是 Ozon 类目字典属性选择器。
根据商品信息，为每个属性从给定 candidates 中选一个最合适的 dictionary_value_id。
硬性规则：
1. 只能输出候选列表中出现的 id；禁止编造 id。
2. 没有合适项时对该属性输出 null（不要勉强选）。
3. 填充物：凉席/藤编/降温垫优先不选或选真实填充材料；不要选「Без наполнителя」除非候选仅此且商品明确无填充。
4. 宠物尺寸：选档位（S/M/L 或 до N кг），不要选整段尺寸描述。
5. 国家默认 Китай（若在候选中）。
只输出 JSON：{"picks":{"<attribute_id>": <dictionary_value_id|null>, ...}}"""


def ai_dict_pick_enabled() -> bool:
    flag = (os.getenv("OZON_AI_DICT_PICK") or "true").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool((os.getenv("DEEPSEEK_API_KEY") or "").strip())


def _high_score_threshold() -> int:
    try:
        return max(100, int(os.getenv("OZON_AI_DICT_HIGH_SCORE", "800")))
    except ValueError:
        return 800


def _max_workers() -> int:
    try:
        return max(2, min(8, int(os.getenv("OZON_AI_DICT_WORKERS", "6"))))
    except ValueError:
        return 6


def _max_candidates() -> int:
    try:
        return max(5, min(20, int(os.getenv("OZON_AI_DICT_MAX_CANDIDATES", "12"))))
    except ValueError:
        return 12


@dataclass
class DictAttrJob:
    attribute_id: int
    name: str
    is_required: bool
    queries: list[str] = field(default_factory=list)
    hint: str = ""


@dataclass
class CandidateBundle:
    attribute_id: int
    name: str
    is_required: bool
    candidates: list[dict[str, Any]]  # {id, value}
    best: dict[str, Any] | None
    best_score: int
    hint: str = ""


def _unique_candidates(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in items:
        vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
        label = str(item.get("value") or "").strip()
        if vid is None or not label or vid in seen:
            continue
        seen.add(vid)
        out.append({"id": vid, "value": label})
        if len(out) >= limit:
            break
    return out


def _score_best(
    candidates: list[dict[str, Any]],
    queries: list[str],
    *,
    attribute_name: str,
    type_id: int,
) -> tuple[dict[str, Any] | None, int]:
    allow_type = _is_type_attr_name(attribute_name)
    best: dict[str, Any] | None = None
    best_score = 0
    for item in candidates:
        vid = int(item["id"])
        label = str(item["value"])
        if allow_type and vid == type_id:
            return (
                {
                    "dictionary_value_id": vid,
                    "value": label,
                    "source": "type_id_match",
                },
                2000,
            )
        for q in queries[:6]:
            score = _score_dict_candidate(q, label)
            if score > best_score:
                best_score = score
                best = {
                    "dictionary_value_id": vid,
                    "value": label,
                    "source": "score",
                }
    return best, best_score


def fetch_candidate_bundle(
    *,
    client: OzonSellerClient,
    job: DictAttrJob,
    description_category_id: int,
    type_id: int,
) -> CandidateBundle:
    """对单个属性：少量 search + 必要时首页枚举，组装候选。"""
    limit = _max_candidates()
    collected: list[dict[str, Any]] = []
    queries = [str(q).strip() for q in job.queries if str(q).strip()][:3]
    if job.hint and job.hint not in queries:
        queries.insert(0, job.hint[:80])

    # Тип：优先用 type_id 直取，减少搜索
    if _is_type_attr_name(job.name):
        try:
            page = client.get_attribute_values(
                attribute_id=job.attribute_id,
                description_category_id=description_category_id,
                type_id=type_id,
                limit=100,
                last_value_id=0,
            )
            values = _parse_value_list(page)
            for item in values:
                vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
                if vid == type_id:
                    label = str(item.get("value") or "").strip()
                    return CandidateBundle(
                        attribute_id=job.attribute_id,
                        name=job.name,
                        is_required=job.is_required,
                        candidates=[{"id": vid, "value": label or str(type_id)}],
                        best={
                            "dictionary_value_id": vid,
                            "value": label or str(type_id),
                            "source": "type_id_match",
                        },
                        best_score=2000,
                        hint=job.hint,
                    )
            collected.extend(values)
        except OzonSellerError:
            pass

    for q in queries:
        if len(q) < 2:
            continue
        try:
            payload = client.search_attribute_values(
                attribute_id=job.attribute_id,
                description_category_id=description_category_id,
                type_id=type_id,
                value=q[:80],
                limit=min(20, limit),
            )
            collected.extend(_parse_value_list(payload))
        except OzonSellerError:
            continue
        # 已有足够候选则不再打后续 search
        if len(_unique_candidates(collected, limit=limit)) >= max(5, limit // 2):
            break

    if len(_unique_candidates(collected, limit=limit)) < 3:
        try:
            page = client.get_attribute_values(
                attribute_id=job.attribute_id,
                description_category_id=description_category_id,
                type_id=type_id,
                limit=100,
                last_value_id=0,
            )
            collected.extend(_parse_value_list(page))
        except OzonSellerError:
            pass

    candidates = _unique_candidates(collected, limit=limit)
    best, best_score = _score_best(
        candidates,
        queries,
        attribute_name=job.name,
        type_id=type_id,
    )
    return CandidateBundle(
        attribute_id=job.attribute_id,
        name=job.name,
        is_required=job.is_required,
        candidates=candidates,
        best=best,
        best_score=best_score,
        hint=job.hint,
    )


def batch_fetch_candidate_bundles(
    *,
    client: OzonSellerClient,
    jobs: list[DictAttrJob],
    description_category_id: int,
    type_id: int,
) -> list[CandidateBundle]:
    if not jobs:
        return []
    if len(jobs) == 1:
        return [
            fetch_candidate_bundle(
                client=client,
                job=jobs[0],
                description_category_id=description_category_id,
                type_id=type_id,
            )
        ]

    results: list[CandidateBundle] = []
    with ThreadPoolExecutor(max_workers=min(_max_workers(), len(jobs))) as pool:
        futures = {
            pool.submit(
                fetch_candidate_bundle,
                client=client,
                job=job,
                description_category_id=description_category_id,
                type_id=type_id,
            ): job.attribute_id
            for job in jobs
        }
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception:
                aid = futures[fut]
                job = next(j for j in jobs if j.attribute_id == aid)
                results.append(
                    CandidateBundle(
                        attribute_id=job.attribute_id,
                        name=job.name,
                        is_required=job.is_required,
                        candidates=[],
                        best=None,
                        best_score=0,
                        hint=job.hint,
                    )
                )
    # 保持与 jobs 相同顺序
    by_id = {b.attribute_id: b for b in results}
    return [by_id[j.attribute_id] for j in jobs if j.attribute_id in by_id]


def _validate_pick(
    bundle: CandidateBundle,
    raw_id: Any,
) -> dict[str, Any] | None:
    vid = _as_int(raw_id)
    if vid is None:
        return None
    for item in bundle.candidates:
        if int(item["id"]) == vid:
            return {
                "dictionary_value_id": vid,
                "value": str(item["value"]),
                "source": "ai_whitelist",
            }
    return None


def ai_select_from_candidates(
    *,
    bundles: list[CandidateBundle],
    product_context: dict[str, Any],
) -> dict[int, dict[str, Any] | None]:
    """一次 AI 调用；返回 attribute_id → pick|None。仅含传入的 bundles。"""
    if not bundles:
        return {}

    payload_attrs = []
    for b in bundles:
        payload_attrs.append(
            {
                "attribute_id": b.attribute_id,
                "name": b.name,
                "required": b.is_required,
                "hint": (b.hint or "")[:80],
                "candidates": [{"id": c["id"], "value": c["value"]} for c in b.candidates],
            }
        )

    user_prompt = (
        "商品上下文：\n"
        f"{json.dumps(product_context, ensure_ascii=False)}\n\n"
        "待选属性（只能从 candidates 选 id）：\n"
        f"{json.dumps(payload_attrs, ensure_ascii=False)}"
    )

    from integrations.deepseek.client import DeepSeekClient, DeepSeekError

    timeout = int(os.getenv("OZON_AI_DICT_TIMEOUT_SECONDS") or "45")
    client = DeepSeekClient(timeout_seconds=timeout)
    try:
        raw = client.chat_json(
            system_prompt=AI_DICT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
        )
    except DeepSeekError:
        return {}
    except Exception:
        return {}

    picks_raw = raw.get("picks") if isinstance(raw, dict) else None
    if not isinstance(picks_raw, dict):
        # 兼容扁平 { "8229": 123 } 或 { "attr_8229": 123 }
        picks_raw = raw if isinstance(raw, dict) else {}

    by_id = {b.attribute_id: b for b in bundles}
    out: dict[int, dict[str, Any] | None] = {}
    for key, value in picks_raw.items():
        aid = _as_int(str(key).replace("attr_", ""))
        if aid is None or aid not in by_id:
            continue
        out[aid] = _validate_pick(by_id[aid], value)
    return out


def resolve_dictionary_picks(
    *,
    client: OzonSellerClient,
    jobs: list[DictAttrJob],
    description_category_id: int,
    type_id: int,
    product_context: dict[str, Any] | None = None,
) -> dict[int, dict[str, Any] | None]:
    """
    解析字典属性最终取值。
    返回 attribute_id → {dictionary_value_id, value, source} | None
    """
    if not jobs:
        return {}

    bundles = batch_fetch_candidate_bundles(
        client=client,
        jobs=jobs,
        description_category_id=description_category_id,
        type_id=type_id,
    )
    threshold = _high_score_threshold()
    resolved: dict[int, dict[str, Any] | None] = {}
    need_ai: list[CandidateBundle] = []

    for b in bundles:
        # Тип / 高分：直接采用
        if b.best and (
            b.best_score >= threshold
            or _is_type_attr_name(b.name)
            or (b.best.get("source") == "type_id_match")
        ):
            resolved[b.attribute_id] = dict(b.best)
            continue
        if not b.candidates:
            resolved[b.attribute_id] = None
            continue
        # 必填或有 hint 的歧义项交给 AI；纯可选且无 hint 可跳过以省时间
        if b.is_required or (b.hint and _norm(b.hint)):
            need_ai.append(b)
        elif b.best and b.best_score >= 50:
            resolved[b.attribute_id] = dict(b.best)
        else:
            resolved[b.attribute_id] = None

    if need_ai and ai_dict_pick_enabled():
        ai_picks = ai_select_from_candidates(
            bundles=need_ai,
            product_context=product_context
            or {
                "title": "",
                "type_id": type_id,
            },
        )
        for b in need_ai:
            picked = ai_picks.get(b.attribute_id)
            if picked:
                resolved[b.attribute_id] = picked
            elif b.best and b.best_score >= 50:
                # AI 未选或非法 id → 回退打分结果
                fallback = dict(b.best)
                fallback["source"] = "score_fallback"
                resolved[b.attribute_id] = fallback
            else:
                resolved[b.attribute_id] = None
    else:
        for b in need_ai:
            if b.best and b.best_score >= 50:
                resolved[b.attribute_id] = dict(b.best)
            else:
                resolved[b.attribute_id] = None

    return resolved
