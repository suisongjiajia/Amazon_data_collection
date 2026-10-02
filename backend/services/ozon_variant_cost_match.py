"""按「本地标题卖什么」匹配 1688 真实货本，避免货号错位导致整梯按外套计价。"""
from __future__ import annotations

import re
from typing import Any

from services.ozon_pricing_service import parse_cny_price

_COVER_RE = re.compile(
    r"чехол|сменн|换洗外套|单独换洗|不含填充|不含楼梯|替换布套|外套|cover",
    re.I,
)
_STAIR_RE = re.compile(
    r"поролон|лестниц|ступен|海绵|宠物楼梯|爬梯|整梯|缓步楼梯|斜坡楼梯|25\s*d",
    re.I,
)
_COLOR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bw", re.compile(r"чёрно[-\s]?бел|черно[-\s]?бел|黑白|чб", re.I)),
    ("beige", re.compile(r"беж|米色|капучино", re.I)),
    ("yg", re.compile(r"жёлто[-\s]?зелён|желто[-\s]?зелен|黄绿", re.I)),
    ("by", re.compile(r"сине[-\s]?жёлт|сине[-\s]?желт|蓝黄", re.I)),
    ("grey", re.compile(r"тёмно[-\s]?сер|темно[-\s]?сер|深灰|серая|серый|серое|(?<![а-яa-z])сер(?![а-яa-z])|灰色|\b灰\b", re.I)),
]

# 30/35/45 = 缓步楼梯；46/55 = 海绵整梯常见高度
_HEIGHT_TO_STEPS = {30: 3, 35: 4, 45: 5, 46: 4, 55: 5}


def _steps_from_text(text: str) -> int | None:
    blob = str(text or "")
    # 俄语显式阶数
    m = re.search(r"([345])\s*ступен", blob, re.I)
    if m:
        return int(m.group(1))
    # 中文：3阶 / 三层 / 四层 / 五层
    m = re.search(r"([345])\s*阶", blob)
    if m:
        return int(m.group(1))
    m = re.search(r"([三四五])\s*层", blob)
    if m:
        return {"三": 3, "四": 4, "五": 5}[m.group(1)]
    # 高度映射
    m = re.search(r"(?:高|высота)[^\d]*(30|35|45|46|55)\s*cm", blob, re.I)
    if m:
        return _HEIGHT_TO_STEPS[int(m.group(1))]
    m = re.search(r"【高(30|35|45|46|55)CM】", blob, re.I)
    if m:
        return _HEIGHT_TO_STEPS[int(m.group(1))]
    return None


def _color_from_text(text: str) -> str | None:
    blob = str(text or "")
    for key, pattern in _COLOR_PATTERNS:
        if pattern.search(blob):
            return key
    return None


def _is_cover(text: str) -> bool | None:
    blob = str(text or "")
    # 明确外套/布套（含 1688「替换布套/不含楼梯」）
    if re.search(r"сменн\w*\s+чехол|без\s+лестниц|换洗外套|单独换洗|不含填充|不含楼梯|替换布套", blob, re.I):
        return True
    if _COVER_RE.search(blob):
        # 「съёмный чехол」只是卖点时，若同时强调整梯且不是 сменный чехол 标题，算整梯
        if _STAIR_RE.search(blob) and not re.search(r"^сменн|^换洗|^外套|^可拆洗替换", blob, re.I):
            return False
        return True
    if _STAIR_RE.search(blob):
        return False
    return None


def parse_listing_spec(*texts: Any) -> dict[str, Any]:
    blob = " | ".join(str(t or "") for t in texts)
    return {
        "is_cover": _is_cover(blob),
        "color": _color_from_text(blob),
        "steps": _steps_from_text(blob),
        "blob": blob[:240],
    }


def parse_raw_1688_spec(row: dict[str, Any]) -> dict[str, Any]:
    title = str(row.get("title") or "")
    size = str(row.get("size") or "")
    color = str(row.get("color") or "")
    va = row.get("variant_attributes") if isinstance(row.get("variant_attributes"), dict) else {}
    spec = str(va.get("规格") or va.get("款式") or va.get("spec") or "")
    # 规格/尺码优先：商品总标题常带「宠物楼梯」，会把外套误判成整梯
    spec_blob = " | ".join(x for x in (size, color, spec) if x)
    full_blob = " | ".join([title, size, color, spec])
    is_cover = _is_cover(spec_blob) if spec_blob.strip() else None
    if is_cover is None:
        is_cover = _is_cover(full_blob)
    return {
        "external_id": str(row.get("external_id") or "").strip(),
        "is_cover": is_cover,
        "color": _color_from_text(spec_blob) or _color_from_text(full_blob),
        "steps": _steps_from_text(spec_blob) or _steps_from_text(full_blob),
        "cost": parse_cny_price(row.get("price_text") or va.get("price_text")),
        "weight_g": _weight_from_row(row),
        "blob": full_blob[:240],
    }


def _weight_from_row(row: dict[str, Any]) -> int | None:
    va = row.get("variant_attributes") if isinstance(row.get("variant_attributes"), dict) else {}
    for key in ("weight_g", "Вес, г", "Вес товара, г", "weight"):
        raw = va.get(key) if key in va else row.get(key)
        if raw is None:
            continue
        try:
            value = int(round(float(str(raw).replace(",", "."))))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _sku_external_id(sku: str) -> str:
    text = str(sku or "").strip()
    if text.startswith("A1688-"):
        return text[6:]
    if text.startswith("OZON-"):
        return text[5:]
    return text


def match_cost_by_listing_title(
    variant: dict[str, Any],
    family: dict[str, Any],
    *,
    edit_title: str | None = None,
) -> dict[str, Any] | None:
    """
    用本地标题（卖什么）去对 1688 规格货本。
    返回 {cost, matched_external_id, is_cover, color, steps, weight_g, reason}
    """
    va = variant.get("variant_attributes") if isinstance(variant.get("variant_attributes"), dict) else {}
    # 优先只看变体标题：variant_attributes 里常残留错乱的颜色/尺码
    local = parse_listing_spec(variant.get("title"))
    if local["color"] is None or local["steps"] is None or local["is_cover"] is None:
        extra = parse_listing_spec(
            va.get("Название цвета"),
            va.get("Цвет"),
            va.get("Размер"),
            va.get("尺码"),
            va.get("区分项"),
        )
        if local["color"] is None:
            local["color"] = extra["color"]
        if local["steps"] is None:
            local["steps"] = extra["steps"]
        if local["is_cover"] is None:
            local["is_cover"] = extra["is_cover"]
    if local["is_cover"] is None or local["steps"] is None:
        fallback = parse_listing_spec(edit_title)
        if local["is_cover"] is None:
            local["is_cover"] = fallback["is_cover"]
        if local["steps"] is None:
            local["steps"] = fallback["steps"]
    raw_rows = [parse_raw_1688_spec(r) for r in (family.get("variants") or [])]
    raw_rows = [r for r in raw_rows if r.get("cost")]
    if not raw_rows:
        return None

    sku = str(variant.get("sku") or "")
    ext = _sku_external_id(sku)

    def _result(row: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "cost": float(row["cost"]),
            "matched_external_id": row["external_id"],
            "is_cover": row["is_cover"],
            "color": row["color"],
            "steps": row["steps"],
            "weight_g": row.get("weight_g"),
            "reason": reason,
            "local": local,
        }

    def _by_sku(rows: list[dict[str, Any]], reason: str) -> dict[str, Any] | None:
        for row in rows:
            if row["external_id"] == ext:
                return _result(row, reason)
        return None

    # 标题能判断整梯/外套时，按标题规格收窄；禁止在过滤失败时直接取全表最低价
    candidates = raw_rows
    steps_applied = False
    if local["is_cover"] is not None:
        filtered = [r for r in candidates if r["is_cover"] is local["is_cover"]]
        if filtered:
            candidates = filtered
    if local["steps"] is not None:
        filtered = [r for r in candidates if r["steps"] == local["steps"]]
        if filtered:
            candidates = filtered
            steps_applied = True
    if local["color"] is not None:
        filtered = [r for r in candidates if r["color"] == local["color"]]
        if filtered:
            candidates = filtered

    # 候选集内优先本 SKU（同阶多色时不会漂到错色最低价）
    sku_in_candidates = _by_sku(candidates, "title_spec_sku")
    if sku_in_candidates:
        return sku_in_candidates

    if len(candidates) == 1:
        return _result(candidates[0], "title_spec_match")

    if local["is_cover"] is not None and steps_applied and candidates:
        best = min(
            candidates,
            key=lambda r: (
                0 if local.get("color") is not None and r.get("color") == local.get("color") else 1,
                r["cost"] or 0,
            ),
        )
        return _result(best, "title_spec_match")

    # 标题信息不完整或过滤未命中：退回货号
    return _by_sku(raw_rows, "sku_fallback")
