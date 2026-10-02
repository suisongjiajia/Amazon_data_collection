from __future__ import annotations

from typing import Any

from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError

# 进程内缓存：type_id -> 所属 description_category_id（官方树父节点）
_TYPE_TO_CATEGORY: dict[int, int] = {}
_TYPE_TO_NAME: dict[int, str] = {}
_TREE_LOADED = False


def _walk_type_parents(nodes: list[Any], parent_category_id: int | None = None) -> None:
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        category_id = node.get("description_category_id")
        try:
            current_category = int(category_id) if category_id is not None else parent_category_id
        except (TypeError, ValueError):
            current_category = parent_category_id

        type_id = node.get("type_id")
        type_name = str(node.get("type_name") or "").strip()
        if type_id is not None and current_category is not None:
            try:
                tid = int(type_id)
                _TYPE_TO_CATEGORY[tid] = int(current_category)
                if type_name:
                    _TYPE_TO_NAME[tid] = type_name
            except (TypeError, ValueError):
                pass

        types = node.get("type") or node.get("types") or []
        if isinstance(types, dict):
            types = [types]
        if isinstance(types, list) and current_category is not None:
            for item in types:
                if not isinstance(item, dict):
                    continue
                tid_raw = item.get("type_id")
                tname = str(item.get("type_name") or "").strip()
                if tid_raw is None:
                    continue
                try:
                    tid = int(tid_raw)
                    _TYPE_TO_CATEGORY[tid] = int(current_category)
                    if tname:
                        _TYPE_TO_NAME[tid] = tname
                except (TypeError, ValueError):
                    continue

        children = node.get("children")
        if isinstance(children, list) and children:
            _walk_type_parents(children, current_category)


def load_type_category_index(*, force: bool = False) -> dict[int, int]:
    """拉取 /v1/description-category/tree，建立 type_id → description_category_id 索引。"""
    global _TREE_LOADED
    if _TREE_LOADED and not force and _TYPE_TO_CATEGORY:
        return _TYPE_TO_CATEGORY

    client = OzonSellerClient()
    last_error: Exception | None = None
    for language in ("DEFAULT", "ZH_HANS", "RU"):
        try:
            payload = client.request(
                "POST",
                "/v1/description-category/tree",
                {"language": language},
            )
            result = payload.get("result")
            if not isinstance(result, list) or not result:
                last_error = OzonSellerError(f"类目树为空 language={language}")
                continue
            _TYPE_TO_CATEGORY.clear()
            _TYPE_TO_NAME.clear()
            _walk_type_parents(result)
            if _TYPE_TO_CATEGORY:
                _TREE_LOADED = True
                return _TYPE_TO_CATEGORY
            last_error = OzonSellerError(f"类目树未解析到 type language={language}")
        except OzonSellerError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return _TYPE_TO_CATEGORY


def find_category_id_for_type(type_id: int | str, *, force_reload: bool = False) -> int | None:
    """根据官方类目树，返回 type 所属的 description_category_id。"""
    try:
        tid = int(str(type_id).strip())
    except (TypeError, ValueError):
        return None
    if tid <= 0:
        return None
    if not force_reload and tid in _TYPE_TO_CATEGORY:
        return _TYPE_TO_CATEGORY[tid]
    index = load_type_category_index(force=force_reload)
    found = index.get(tid)
    if found is not None:
        return found
    if not force_reload:
        index = load_type_category_index(force=True)
        return index.get(tid)
    return None


def find_type_name(type_id: int | str, *, force_reload: bool = False) -> str | None:
    try:
        tid = int(str(type_id).strip())
    except (TypeError, ValueError):
        return None
    if tid <= 0:
        return None
    if not force_reload and tid in _TYPE_TO_NAME:
        return _TYPE_TO_NAME[tid]
    load_type_category_index(force=force_reload)
    name = _TYPE_TO_NAME.get(tid)
    if name:
        return name
    if not force_reload:
        load_type_category_index(force=True)
        return _TYPE_TO_NAME.get(tid)
    return None


# 标题/属性关键词 → type（顺序：越具体越靠前）
_TYPE_KEYWORD_RULES: tuple[tuple[int, tuple[str, ...]], ...] = (
    (98056, ("автогамак", "гамак", "车载", "汽车吊床")),
    (95204, ("лестниц", "ступен", "пандус", "трап", "爬梯", "宠物楼梯", "缓步楼梯")),
    (95199, ("домик", "ракуш", "гнезд", "тоннел", "shell", "贝壳", "猫窝", "半封闭", "封闭式")),
    (95196, ("будка",)),
    (95203, ("подстилк", "лежак-мат", "матрас", "коврик", "凉席", "睡垫", "垫子")),
    (95203, ("лежак", "мат")),
)


def suggest_type_id_from_text(*texts: Any, current_type_id: int | str | None = None) -> int | None:
    """
    根据标题/规格推断更合适的 type_id。
    当前 type 与文案冲突时返回建议值（贝壳窝≠汽车吊床，垫子≠狗窝）。
    """
    blob = " ".join(str(t or "") for t in texts).casefold()
    if not blob.strip():
        return None
    load_type_category_index()

    suggested: int | None = None
    for type_id, keywords in _TYPE_KEYWORD_RULES:
        if any(k.casefold() in blob for k in keywords):
            suggested = type_id
            break
    if suggested is None:
        return None

    try:
        current = int(str(current_type_id).strip()) if current_type_id is not None else None
    except (TypeError, ValueError):
        current = None
    if current is None or current <= 0:
        return suggested
    if current == suggested:
        return None

    current_name = (_TYPE_TO_NAME.get(current) or "").casefold()

    # 当前类型族与文案证据冲突 → 纠正
    is_hammock_type = any(t in current_name for t in ("гамак", "автогамак"))
    is_booth_type = "будка" in current_name
    is_house_type = "домик" in current_name
    is_bed_type = any(t in current_name for t in ("лежак", "подстилк", "матрас"))

    has_hammock = any(t in blob for t in ("гамак", "автогамак", "车载"))
    has_house = any(t in blob for t in ("домик", "ракуш", "гнезд", "тоннел", "贝壳", "猫窝", "半封闭", "закрыт"))
    has_booth = "будка" in blob
    has_mat = any(t in blob for t in ("подстилк", "мат", "матрас", "коврик", "凉席", "睡垫", "垫子"))
    has_stair = any(t in blob for t in ("лестниц", "ступен", "пандус", "трап", "爬梯", "宠物楼梯"))
    is_stair_type = "лестниц" in current_name
    is_net_or_misc = any(t in current_name for t in ("сетк", "фиксатор", "гамак"))

    if has_stair and suggested == 95204 and current != 95204:
        return suggested
    if is_stair_type and has_stair:
        return None
    if is_hammock_type and not has_hammock:
        return suggested
    if is_net_or_misc and has_house and suggested == 95199:
        return suggested
    if is_booth_type and has_house and not has_booth:
        return suggested
    if is_booth_type and has_mat and not has_booth and not has_house:
        return suggested
    if is_bed_type and has_house and suggested == 95199:
        # 标题明确是窝/屋时切到 Домик；仅「лежак-мат」才保留床垫类
        if any(t in blob for t in ("домик", "猫窝", "закрыт", "полузакрыт", "утепл")):
            return suggested
        if any(t in blob for t in ("подстилк", "мат", "ротанга", "ротанг", "凉席", "cooling")):
            return None
        return suggested
    if is_house_type and has_mat and not has_house and suggested == 95203:
        return suggested
    if has_house and suggested == 95199 and current != 95199:
        if is_bed_type and not any(t in blob for t in ("домик", "猫窝", "закрыт")):
            return None
        return suggested
    if has_mat and not has_house and not has_booth and not has_stair and suggested == 95203 and current != 95203:
        return suggested

    return None


def correct_category_id_for_type(
    *,
    description_category_id: int | str | None,
    type_id: int | str | None,
) -> tuple[str | None, str | None, bool]:
    """
    用官方树校正 (description_category_id, type_id)。
    返回 (category_id, type_id, changed)。
    """
    type_text = str(type_id or "").strip()
    category_text = str(description_category_id or "").strip()
    if not type_text.isdigit():
        return (category_text or None, type_text or None, False)

    parent = find_category_id_for_type(type_text)
    if parent is None:
        return (category_text or None, type_text, False)

    parent_text = str(parent)
    if category_text != parent_text:
        return parent_text, type_text, True
    return category_text, type_text, False


def _tokenize_query(text: str) -> list[str]:
    import re

    raw = str(text or "").strip().lower()
    if not raw:
        return []
    parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zа-яё0-9]{2,}", raw, flags=re.I)
    # 中文再切 2-gram，提高「宠物隧道」这类命中
    grams: list[str] = []
    for part in parts:
        if re.fullmatch(r"[\u4e00-\u9fff]+", part) and len(part) >= 4:
            for index in range(len(part) - 1):
                grams.append(part[index : index + 2])
        grams.append(part)
    seen: set[str] = set()
    out: list[str] = []
    for item in grams:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out[:40]


def search_types_by_query(query: str, *, limit: int = 12) -> list[dict[str, Any]]:
    """按标题/关键词在官方类目树 type_name 里打分检索。"""
    load_type_category_index(force=False)
    if not _TYPE_TO_NAME:
        load_type_category_index(force=True)
    tokens = _tokenize_query(query)
    if not tokens:
        return []
    query_norm = str(query or "").strip().lower()
    scored: list[dict[str, Any]] = []
    for type_id, type_name in _TYPE_TO_NAME.items():
        name = str(type_name or "").strip()
        if not name:
            continue
        name_l = name.lower()
        score = 0
        if query_norm and (query_norm in name_l or name_l in query_norm):
            score += 100
        for token in tokens:
            if token in name_l:
                score += 8 + min(len(token), 6)
        if score <= 0:
            continue
        category_id = _TYPE_TO_CATEGORY.get(type_id)
        scored.append(
            {
                "type_id": int(type_id),
                "type_name": name,
                "description_category_id": int(category_id) if category_id is not None else None,
                "score": score,
            }
        )
    scored.sort(key=lambda item: (-int(item["score"]), str(item["type_name"])))
    return scored[: max(1, min(limit, 30))]
