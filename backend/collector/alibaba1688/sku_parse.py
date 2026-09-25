"""解析 1688 SKU 选择器：支持双（多）区分项笛卡尔积。"""

from __future__ import annotations

import html
import re
from typing import Any


def _dig_first(obj: Any, key: str, *, depth: int = 0) -> Any:
    if depth > 10 or obj is None:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _dig_first(value, key, depth=depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj[:40]:
            found = _dig_first(item, key, depth=depth + 1)
            if found is not None:
                return found
    return None


def _plain(text: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(text or "")).replace("&gt;", ">")).strip()


def _split_axes(spec_attrs: Any) -> list[str]:
    """specAttrs 常见为「棕色小熊>S(33*30*32CM)」或 HTML 实体。"""
    raw = _plain(spec_attrs)
    if not raw:
        return []
    if ">" in raw:
        return [part.strip() for part in raw.split(">") if part.strip()]
    if ">>" in raw:
        return [part.strip() for part in raw.split(">>") if part.strip()]
    return [raw]


def looks_like_size(text: Any) -> bool:
    value = _plain(text)
    if not value:
        return False
    if re.search(r"(尺码|尺寸|码数|建议\d+斤|[SMLX]{1,3}\s*\(|\d+\s*[x×*]\s*\d+\s*[x×*]?\s*\d*\s*cm)", value, re.I):
        return True
    if re.fullmatch(r"[SMLX]{1,3}", value, re.I):
        return True
    if re.search(r"\d+\s*cm", value, re.I) and re.search(r"[SMLX]|\d+\s*[x×*]", value, re.I):
        return True
    return False


def looks_like_style(text: Any) -> bool:
    value = _plain(text)
    if not value or looks_like_size(value):
        return False
    # 含颜色字或款式描述
    if re.search(r"[色系]|小熊|长耳朵|条纹|印花|款|型", value):
        return True
    if re.search(r"(红|橙|黄|绿|青|蓝|紫|黑|白|灰|粉|棕|米|卡其|咖啡|藏青)", value):
        return True
    return len(value) <= 40


def _classify_prop(prop_name: str, values: list[str]) -> str:
    """返回 color / size / other。以选项内容为准，不盲信「颜色」标签。"""
    name = _plain(prop_name)
    samples = values[:8]
    size_hits = sum(1 for v in samples if looks_like_size(v))
    style_hits = sum(1 for v in samples if looks_like_style(v))
    if size_hits >= max(1, len(samples) // 2):
        return "size"
    if style_hits >= max(1, len(samples) // 2):
        return "color"
    if re.search(r"尺码|尺寸|大小|规格尺寸", name):
        return "size"
    if re.search(r"颜色|款式|花色|规格|型号", name):
        # 「颜色」里全是尺码时上面已判 size；这里当款式/颜色
        return "color"
    return "other"


def _abs_image(url: Any) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("http"):
        return text
    return f"https://cbu01.alicdn.com/{text.lstrip('/')}"


def _iter_sku_map_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[Any] = []
    sku_map = _dig_first(payload, "skuMap")
    if isinstance(sku_map, list):
        entries = list(sku_map)
    elif isinstance(sku_map, dict):
        # 有的实现 key 是 specAttrs，value 是详情
        for key, value in sku_map.items():
            if isinstance(value, dict):
                row = dict(value)
                if not row.get("specAttrs") and not row.get("name"):
                    row["specAttrs"] = key
                entries.append(row)
            elif isinstance(value, (str, int, float)):
                continue
    info_map = _dig_first(payload, "skuInfoMap")
    if isinstance(info_map, dict):
        mapped: list[dict[str, Any]] = []
        for key, value in info_map.items():
            if isinstance(value, dict):
                row = dict(value)
                if not row.get("specAttrs") and not row.get("name"):
                    row["specAttrs"] = key
                mapped.append(row)
        if mapped:
            entries = mapped
    return [item for item in entries if isinstance(item, dict)]


def parse_sku_selector_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    解析 mtop.1688.wosc.queryOfferSkuSelectorModel。

    双区分项（如 规格×「颜色」实为尺码）以 skuMap/skuInfoMap 的完整组合为准，
    不要把各轴选项摊平成假 SKU。
    """
    if not isinstance(payload, dict):
        return []

    props_raw = _dig_first(payload, "skuProps")
    props: list[dict[str, Any]] = []
    image_by_value: dict[str, str] = {}
    if isinstance(props_raw, list):
        for prop in props_raw:
            if not isinstance(prop, dict):
                continue
            prop_name = _plain(prop.get("prop") or prop.get("name") or prop.get("label") or "")
            values_out: list[dict[str, str]] = []
            values = prop.get("value")
            if not isinstance(values, list):
                continue
            names: list[str] = []
            for item in values:
                if not isinstance(item, dict):
                    continue
                name = _plain(item.get("name"))
                if not name:
                    continue
                names.append(name)
                img = _abs_image(item.get("imageUrl") or item.get("image"))
                if img:
                    image_by_value[name] = img
                values_out.append({"name": name, "image_url": img})
            if not names:
                continue
            props.append(
                {
                    "name": prop_name or f"轴{len(props) + 1}",
                    "kind": _classify_prop(prop_name, names),
                    "values": values_out,
                }
            )

    weight_by_sku_id: dict[str, int] = {}
    sku_weight = _dig_first(payload, "skuWeight")
    if isinstance(sku_weight, dict):
        for key, value in sku_weight.items():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number <= 0:
                continue
            grams = int(round(number * 1000)) if number < 100 else int(round(number))
            weight_by_sku_id[str(key)] = grams

    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for item in _iter_sku_map_entries(payload):
        axes = _split_axes(item.get("specAttrs") or item.get("name"))
        if not axes:
            continue
        # 按 props 顺序对齐；数量不一致时仍保留全部轴值
        color_value = ""
        size_value = ""
        other_parts: list[str] = []
        image_url = ""
        for index, axis_value in enumerate(axes):
            kind = "other"
            if index < len(props):
                kind = str(props[index].get("kind") or "other")
            elif looks_like_size(axis_value):
                kind = "size"
            elif looks_like_style(axis_value):
                kind = "color"
            if kind == "size" and not size_value:
                size_value = axis_value
            elif kind == "color" and not color_value:
                color_value = axis_value
            else:
                other_parts.append(axis_value)
            if not image_url and axis_value in image_by_value:
                image_url = image_by_value[axis_value]

        # 语义兜底：一轴像尺码、一轴像款式
        if len(axes) >= 2 and (not color_value or not size_value):
            for axis_value in axes:
                if not size_value and looks_like_size(axis_value):
                    size_value = axis_value
                elif not color_value and looks_like_style(axis_value):
                    color_value = axis_value

        if not color_value and not size_value:
            color_value = axes[0]
            if len(axes) > 1:
                size_value = axes[1]

        label_parts = [part for part in (color_value, size_value, *other_parts) if part]
        # 去重保序
        label_parts = list(dict.fromkeys(label_parts))
        label = " / ".join(label_parts) if label_parts else axes[0]
        dedupe_key = ">".join(axes)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        price = item.get("discountPrice") or item.get("price") or item.get("multiPrice")
        price_text = f"¥{price}" if price not in (None, "") else None
        sku_id = item.get("skuId") or item.get("specId")
        weight_g = weight_by_sku_id.get(str(sku_id)) if sku_id not in (None, "") else None

        rows.append(
            {
                "label": label,
                "color": color_value or None,
                "size": size_value or None,
                "spec_axes": axes,
                "price_text": price_text,
                "image_url": image_url or None,
                "sku_id": str(sku_id) if sku_id not in (None, "") else None,
                "weight_g": str(int(weight_g)) if weight_g else None,
                "axis_props": [
                    {"name": p.get("name"), "kind": p.get("kind")} for p in props
                ],
            }
        )

    # skuMap 缺失时：仅单轴才用 props 摊平；双轴则做笛卡尔积占位（无价）
    if not rows and props:
        if len(props) == 1:
            for value in props[0]["values"]:
                name = value["name"]
                rows.append(
                    {
                        "label": name,
                        "color": name if props[0]["kind"] != "size" else None,
                        "size": name if props[0]["kind"] == "size" else None,
                        "spec_axes": [name],
                        "price_text": None,
                        "image_url": value.get("image_url") or None,
                        "sku_id": None,
                        "weight_g": None,
                    }
                )
        elif len(props) == 2:
            for left in props[0]["values"]:
                for right in props[1]["values"]:
                    axes = [left["name"], right["name"]]
                    color_value = left["name"] if props[0]["kind"] != "size" else (
                        right["name"] if props[1]["kind"] != "size" else left["name"]
                    )
                    size_value = ""
                    if props[0]["kind"] == "size":
                        size_value = left["name"]
                    elif props[1]["kind"] == "size":
                        size_value = right["name"]
                    image_url = left.get("image_url") or right.get("image_url") or ""
                    label = " / ".join(
                        part for part in (color_value, size_value) if part
                    ) or " / ".join(axes)
                    rows.append(
                        {
                            "label": label,
                            "color": color_value or None,
                            "size": size_value or None,
                            "spec_axes": axes,
                            "price_text": None,
                            "image_url": image_url or None,
                            "sku_id": None,
                            "weight_g": None,
                        }
                    )

    return rows


def merge_pack_into_skus(
    skus: list[dict[str, Any]],
    pack_rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """把包装表长宽高/重量合并进 SKU（按颜色/规格/尺码模糊匹配）。"""
    packs: list[dict[str, Any]] = [row for row in (pack_rows or []) if isinstance(row, dict)]

    def _pack_key(row: dict[str, Any]) -> str:
        return _plain(row.get("color") or row.get("spec") or row.get("label") or "")

    pack_by_key = {_pack_key(row): row for row in packs if _pack_key(row)}

    if not skus and pack_by_key:
        skus = [{"label": k, "color": k} for k in pack_by_key]

    out: list[dict[str, Any]] = []
    for sku in skus:
        item = dict(sku)
        candidates = [
            _plain(item.get("label")),
            _plain(item.get("color")),
            _plain(item.get("size")),
            *[_plain(x) for x in (item.get("spec_axes") or [])],
        ]
        pack = None
        for key in candidates:
            if key and key in pack_by_key:
                pack = pack_by_key[key]
                break
        if pack is None:
            # 尺码行常与 size 文案部分重合
            size_text = _plain(item.get("size"))
            for key, row in pack_by_key.items():
                if size_text and (size_text in key or key in size_text):
                    pack = row
                    break
                color_text = _plain(item.get("color"))
                if color_text and (color_text in key or key in color_text):
                    pack = row
                    break
        if pack:
            for field in ("length_cm", "width_cm", "height_cm", "volume_cm3", "spec"):
                if pack.get(field) not in (None, "") and item.get(field) in (None, ""):
                    item[field] = pack[field]
            if pack.get("weight_g") not in (None, "") and item.get("weight_g") in (None, ""):
                item["weight_g"] = pack["weight_g"]
        out.append(item)
    return out
