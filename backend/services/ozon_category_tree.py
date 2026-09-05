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
