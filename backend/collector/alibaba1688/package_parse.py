from __future__ import annotations

import re
from typing import Any


def _first_number(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(text or "").replace(",", "."))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_weight_to_grams(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    number = _first_number(text)
    if number is None or number <= 0:
        return None
    if "kg" in text or "千克" in text or "公斤" in text:
        return max(1, int(round(number * 1000)))
    if "斤" in text:
        return max(1, int(round(number * 500)))
    # 默认按克；若数字很小且带「克」明确，或 > 20 当克
    return max(1, int(round(number)))


def parse_size_to_mm(value: Any) -> tuple[int | None, int | None, int | None]:
    """解析 30x20x10cm / 300*200*100mm / 长30宽20高10 等。要求明确三维分隔，避免误吃时间/运费。"""
    text = str(value or "").strip().lower().replace("×", "x").replace("*", "x").replace("х", "x")
    if not text:
        return None, None, None
    # 必须有 x 分隔的三维，或「长…宽…高…」
    triple = re.search(
        r"(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)",
        text.replace(",", "."),
    )
    if not triple:
        labeled = re.search(
            r"长\s*[:=]?\s*(\d+(?:\.\d+)?)\D{0,8}宽\s*[:=]?\s*(\d+(?:\.\d+)?)\D{0,8}高\s*[:=]?\s*(\d+(?:\.\d+)?)",
            text.replace(",", "."),
        )
        if not labeled:
            return None, None, None
        a, b, c = float(labeled.group(1)), float(labeled.group(2)), float(labeled.group(3))
    else:
        a, b, c = float(triple.group(1)), float(triple.group(2)), float(triple.group(3))

    unit_mm = "mm" in text or "毫米" in text
    unit_cm = "cm" in text or "厘米" in text or "公分" in text
    if unit_mm:
        scale = 1.0
    elif unit_cm or max(a, b, c) < 200:
        scale = 10.0
    else:
        scale = 1.0
    depth = max(1, int(round(a * scale)))
    width = max(1, int(round(b * scale)))
    height = max(1, int(round(c * scale)))
    # 过滤明显垃圾（如 1mm）
    if min(depth, width, height) < 5 and max(depth, width, height) < 50:
        return None, None, None
    return depth, width, height


def pack_rows_to_metrics(rows: list[dict[str, Any]] | None) -> dict[str, int]:
    """取包装表第一行（或重量最大行）作为默认包裹。"""
    if not rows:
        return {}
    best = None
    best_w = -1
    for row in rows:
        try:
            w = int(float(row.get("weight_g") or 0))
        except (TypeError, ValueError):
            w = 0
        if w > best_w:
            best_w = w
            best = row
    row = best or rows[0]
    try:
        l_cm = float(row.get("length_cm") or 0)
        w_cm = float(row.get("width_cm") or 0)
        h_cm = float(row.get("height_cm") or 0)
        weight_g = int(float(row.get("weight_g") or 0))
    except (TypeError, ValueError):
        return {}
    if l_cm <= 0 or w_cm <= 0 or h_cm <= 0 or weight_g <= 0:
        return {}
    return {
        "depth_mm": max(1, int(round(l_cm * 10))),
        "width_mm": max(1, int(round(w_cm * 10))),
        "height_mm": max(1, int(round(h_cm * 10))),
        "weight_g": weight_g,
    }


def extract_package_metrics(
    attributes: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, int]:
    """
    从 1688 详情属性里取包装长宽高(mm)与重量(g)。
    优先用「包装信息」表格；找不到的字段不返回。
    """
    attrs = dict(attributes or {})
    detail = dict(detail or {})

    pack_rows = detail.get("pack_rows")
    if not isinstance(pack_rows, list):
        pack_rows = attrs.get("pack_rows")
    if isinstance(pack_rows, list) and pack_rows:
        from_table = pack_rows_to_metrics(pack_rows)
        if from_table:
            return from_table

    blob_items: list[tuple[str, str]] = []
    for key, value in {**attrs, **{k: detail.get(k) for k in ("weight", "package", "volume", "unit_weight")}}.items():
        if value is None or key == "pack_rows":
            continue
        blob_items.append((str(key), str(value)))

    weight: int | None = None
    depth = width = height = None

    for key, value in blob_items:
        key_l = key.lower()
        if any(token in key_l for token in ("重量", "净重", "毛重", "weight", "кг", "вес")):
            parsed = parse_weight_to_grams(value)
            if parsed:
                weight = parsed
        if any(
            token in key_l
            for token in ("包装尺寸", "外箱", "长宽高", "package", "габарит")
        ):
            d, w, h = parse_size_to_mm(value)
            if d and w and h:
                depth, width, height = d, w, h

    if weight is None:
        for key in ("weight", "unit_weight", "weight_g"):
            parsed = parse_weight_to_grams(detail.get(key))
            if parsed:
                weight = parsed
                break
    if depth is None:
        for key in ("package", "package_size"):
            d, w, h = parse_size_to_mm(detail.get(key))
            if d and w and h:
                depth, width, height = d, w, h
                break

    if depth is None:
        for _key, value in blob_items:
            d, w, h = parse_size_to_mm(value)
            if d and w and h:
                depth, width, height = d, w, h
                break

    out: dict[str, int] = {}
    if depth and width and height:
        out["depth_mm"] = depth
        out["width_mm"] = width
        out["height_mm"] = height
    if weight:
        out["weight_g"] = weight
    return out
