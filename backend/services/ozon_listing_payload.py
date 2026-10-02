from __future__ import annotations

import os
import re
from typing import Any

from integrations.ozon_seller.client import OzonSellerError

# 全站统一包裹尺寸（避免 Ozon INCORRECT_DENSITY / 库存侧尺寸校验）
DEFAULT_PACKAGE_DEPTH_MM = 100
DEFAULT_PACKAGE_WIDTH_MM = 100
DEFAULT_PACKAGE_HEIGHT_MM = 100
DEFAULT_PACKAGE_WEIGHT_G = 200


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def force_package_metrics_enabled() -> bool:
    # 默认关闭：必须用库里的真实包装尺寸，再按兴远尺寸档抬重量
    raw = (os.getenv("OZON_FORCE_PACKAGE_METRICS") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_fixed_package_metrics() -> tuple[int, int, int, int]:
    """返回 (长mm, 宽mm, 高mm, 重量g)。"""
    return (
        max(1, _env_int("OZON_FIXED_DEPTH_MM", DEFAULT_PACKAGE_DEPTH_MM)),
        max(1, _env_int("OZON_FIXED_WIDTH_MM", DEFAULT_PACKAGE_WIDTH_MM)),
        max(1, _env_int("OZON_FIXED_HEIGHT_MM", DEFAULT_PACKAGE_HEIGHT_MM)),
        max(1, _env_int("OZON_FIXED_WEIGHT_G", DEFAULT_PACKAGE_WEIGHT_G)),
    )


def package_is_manual(attributes: dict[str, Any] | None) -> bool:
    """审核中心手改过尺寸后，不再被全局默认值覆盖。"""
    flag = str((attributes or {}).get("package_manual") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_SIZE_LETTER_RE = re.compile(r"\b(XXL|XL|XS|S|M|L)\b", re.I)
_DIMS_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[x×х*]\s*(\d+(?:[.,]\d+)?)",
    re.I,
)
_DIMS_BLOCK_RE = re.compile(
    r"(?:,\s*)?(?:размер\s*)?(?:XXL|XL|XS|S|M|L)?\s*"
    r"\d+(?:[.,]\d+)?\s*[x×х*]\s*\d+(?:[.,]\d+)?(?:\s*[x×х*]\s*\d+(?:[.,]\d+)?)?"
    r"\s*(?:см|cm|мм|mm)?",
    re.I,
)
_WEIGHT_HINT_RE = re.compile(
    r"\([^)]*(?:цзин|斤|кг|kg|до\s*\d+)[^)]*\)",
    re.I,
)


def _cyrillic_count(text: str) -> int:
    return len(_CYRILLIC_RE.findall(text or ""))


def _strip_size_and_weight_noise(text: str) -> str:
    """去掉名称中的尺寸/斤数提示，避免「70x100 … 30x40」双尺寸和「цзиней」。"""
    cleaned = str(text or "")
    cleaned = _WEIGHT_HINT_RE.sub("", cleaned)
    cleaned = _DIMS_BLOCK_RE.sub("", cleaned)
    cleaned = _SIZE_LETTER_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    return cleaned.strip(" ,/;|-")


def _extract_size_dims_cm(*texts: Any) -> str:
    """提取「41x50 см」，不含拉丁尺码字母（避免 Ozon 名称拉丁/大写校验）。"""
    from services.ozon_attribute_fill import listing_size_label

    for raw in texts:
        label = listing_size_label(raw) if raw else ""
        for candidate in (label, str(raw or "")):
            # 忽略明显的包装默认 10x10
            matched = _DIMS_RE.search(candidate)
            if matched:
                try:
                    a = int(float(matched.group(1).replace(",", ".")))
                    b = int(float(matched.group(2).replace(",", ".")))
                except ValueError:
                    continue
                if a <= 15 and b <= 15:
                    continue
                return f"{a}x{b} см"
    return ""


def build_ozon_item_name(
    *,
    variant_title: str,
    edit_title: str,
    color: str = "",
    size_hint: str = "",
    type_name: str = "",
) -> str:
    """
    Ozon 商品名称规则：
    - 必须以西里尔文为主，不能是拉丁字母串
    - 不能有大量大写拉丁字母
    - 只保留一套尺寸；类型词尽量与 type_name 一致
    - 名称必须能体现 Тип（如 Лестница / Домик），否则会 DESCRIPTION_DECLINE
    中文变体标题 strip 后会变成「M:41*50」，严禁直接提交。
    """
    from services.ozon_attribute_fill import contains_cjk, listing_color_label

    def _has_type_signal(text: str, type_label: str) -> bool:
        name_l = str(text or "").casefold()
        type_l = str(type_label or "").casefold()
        if not type_l:
            return True
        tokens = (
            "лестниц",
            "ступен",
            "домик",
            "лежак",
            "подстилк",
            "будка",
            "гамак",
            "тоннел",
            "коврик",
            "матрас",
        )
        type_tokens = [t for t in tokens if t in type_l]
        if not type_tokens:
            first = type_l.split()[0] if type_l.split() else ""
            return bool(first and first in name_l)
        return any(t in name_l for t in type_tokens)

    type_l = str(type_name or "").strip()
    base = ""
    for cand in (variant_title, edit_title):
        text = str(cand or "").strip()
        if not text or contains_cjk(text):
            continue
        if _cyrillic_count(text) < 8:
            continue
        # 变体标题若只有颜色/尺码（无 лестница/домик），不能当主名称
        if type_l and not _has_type_signal(text, type_l) and cand == variant_title:
            continue
        base = text
        break
    if not base:
        for cand in (edit_title, type_l, "Лежанка для животных"):
            text = str(cand or "").strip()
            if text and not contains_cjk(text) and _cyrillic_count(text) >= 4:
                base = text
                break
        if not base:
            base = "Лежанка для животных"

    base = _strip_size_and_weight_noise(base)
    # 若有官方类型名，避免名称用冲突类型词（如 type=Лежак 却写 Будка）
    if type_l:
        conflict_pairs = (
            (("будка",), ("лежак", "подстилк", "мат", "домик")),
            (("домик",), ("будка",)),
            (("автогамак", "гамак"), ("будка", "домик")),
            (("лестниц",), ("домик", "гамак", "будка")),
        )
        base_l = base.casefold()
        type_l_cf = type_l.casefold()
        for type_tokens, name_tokens in conflict_pairs:
            if any(t in type_l_cf for t in type_tokens) and any(t in base_l for t in name_tokens):
                base = type_l
                break
            if any(t in type_l_cf for t in ("лежак", "подстилк")) and any(
                t in base_l for t in ("будка",)
            ):
                base = type_l
                break
        # 最终兜底：名称仍无类型信号时，用类型名做主干
        if not _has_type_signal(base, type_l):
            base = type_l

    color_ru = ""
    if color:
        color_ru = listing_color_label(color, variant_title, edit_title)
    if color_ru and (contains_cjk(color_ru) or _cyrillic_count(color_ru) < 2):
        color_ru = ""

    # 尺寸只信任 size_hint（通常来自 规格），避免标题与规格两套尺寸拼在一起
    dims = _extract_size_dims_cm(size_hint) or _extract_size_dims_cm(variant_title)
    # 阶数也拼进名称，便于区分变体
    steps = ""
    step_match = re.search(r"(\d+)\s*ступен", f"{variant_title} {size_hint}", flags=re.I)
    if step_match:
        steps = f"{step_match.group(1)} ступени"

    parts = [base]
    if color_ru and color_ru.casefold() not in base.casefold():
        parts.append(color_ru)
    if steps and steps.casefold() not in " ".join(parts).casefold():
        parts.append(steps)
    if dims:
        parts.append(dims)

    name = ", ".join(p for p in parts if p)
    name = _strip_size_and_weight_noise(name)
    if dims and dims not in name:
        name = f"{name}, {dims}" if name else dims
    name = _SIZE_LETTER_RE.sub("", name)
    name = "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in name)
    name = re.sub(r"\s{2,}", " ", name)
    name = re.sub(r"\s*,\s*", ", ", name).strip(" ,/")
    if _cyrillic_count(name) < 8 or (type_l and not _has_type_signal(name, type_l)):
        fallback = str(type_name or "Лежанка для животных").strip()
        extra = ", ".join(p for p in (color_ru, steps, dims) if p)
        name = f"{fallback}, {extra}" if extra else fallback
    return name[:200]


def apply_fixed_package_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """把统一尺寸/重量写入 attributes（覆盖原值）。手改过的保留。"""
    attrs = dict(attributes or {})
    if package_is_manual(attrs):
        return attrs
    depth, width, height, weight = get_fixed_package_metrics()
    attrs["Длина, мм"] = str(depth)
    attrs["Ширина, мм"] = str(width)
    attrs["Высота, мм"] = str(height)
    attrs["Вес, г"] = str(weight)
    attrs["Вес товара, г"] = str(weight)
    attrs["Вес с упаковкой, г"] = str(weight)
    attrs["depth_mm"] = str(depth)
    attrs["width_mm"] = str(width)
    attrs["height_mm"] = str(height)
    attrs["length_mm"] = str(depth)
    attrs["weight_g"] = str(weight)
    attrs["weight"] = str(weight)
    attrs["Размеры, мм"] = f"{depth}*{width}*{height}"
    attrs["Размер упаковки (Длина х Ширина х Высота), см"] = (
        f"{max(1, round(depth / 10))}x{max(1, round(width / 10))}x{max(1, round(height / 10))}"
    )
    return attrs


def _parse_dimension_mm(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return None
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    lower = text.lower()
    # 「85 см」是厘米，不能直接当成 85 毫米
    if any(unit in lower for unit in ("см", "cm", "厘米")) and not any(
        unit in lower for unit in ("мм", "mm", "毫米")
    ):
        number *= 10
    return int(number)


def parse_size_triplet_mm(value: Any) -> tuple[int | None, int | None, int | None]:
    """
    解析 '360*360' / '330x330x330' / '420×420' 等为 (长, 宽, 高) mm。
    仅两个数时按立方体补齐高度（猫窝等常见）。
    """
    text = str(value or "").strip()
    if not text:
        return None, None, None
    parts = re.split(r"[*x×хX/\s,;]+", text)
    nums: list[int] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        num = _parse_dimension_mm(part)
        if num is not None:
            nums.append(num)
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]
    if len(nums) == 2:
        return nums[0], nums[1], nums[0]
    return None, None, None


def _is_net_product_key(key: str) -> bool:
    """净品尺寸不能被当成包裹长宽高。"""
    text = str(key)
    lower = text.lower()
    return lower.startswith("net_") or "净品" in text or "товара" in lower or "изделия" in lower


def read_net_product_mm(attributes: dict[str, Any] | None) -> tuple[int | None, int | None, int | None]:
    attrs = attributes or {}
    depth = _parse_dimension_mm(attrs.get("net_depth_mm"))
    width = _parse_dimension_mm(attrs.get("net_width_mm"))
    height = _parse_dimension_mm(attrs.get("net_height_mm"))
    if depth and width and height:
        return depth, width, height
    return None, None, None


def _parse_dimensions_from_attributes(attributes: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    depth = None
    width = None
    height = None
    for key, value in attributes.items():
        if _is_net_product_key(str(key)) or not _is_explicit_package_key(str(key)):
            continue
        lower = str(key).lower()
        # 组合尺寸字段（如 Размеры, мм=360*360）优先拆分
        if any(alias in lower for alias in ("размер", "size", "尺寸", "габарит")) and not any(
            alias in lower for alias in ("длина", "ширина", "высота", "length", "width", "height")
        ):
            d, w, h = parse_size_triplet_mm(value)
            if d is not None:
                depth = depth or d
            if w is not None:
                width = width or w
            if h is not None:
                height = height or h
            continue
        if any(alias in lower for alias in ("длина", "length", "长度", "depth")):
            depth = _parse_dimension_mm(value) or depth
        if any(alias in lower for alias in ("ширина", "width", "宽度")):
            width = _parse_dimension_mm(value) or width
        if any(alias in lower for alias in ("высота", "height", "高度")):
            height = _parse_dimension_mm(value) or height
        # 专用字段（商品编辑页）
        if lower in {"length_mm", "depth_mm"}:
            depth = _parse_dimension_mm(value) or depth
        if lower == "width_mm":
            width = _parse_dimension_mm(value) or width
        if lower == "height_mm":
            height = _parse_dimension_mm(value) or height

    size_text = attributes.get("size") or attributes.get("尺寸")
    if isinstance(size_text, str) and any(sep in size_text for sep in ("×", "*", "x", "х")):
        d, w, h = parse_size_triplet_mm(size_text)
        depth = depth or d
        width = width or w
        height = height or h
    return depth, width, height


def _parse_weight_grams(attributes: dict[str, Any], size_weight: str | None = None) -> int | None:
    for key, value in attributes.items():
        lower = str(key).lower()
        if lower == "weight_g" or any(alias in lower for alias in ("вес", "weight", "重量", "масса")):
            text = str(value).lower()
            num = _parse_dimension_mm(value)
            if num is None:
                continue
            if "kg" in text or "кг" in text or "千克" in text:
                return int(num * 1000)
            return num
    if size_weight:
        num = _parse_dimension_mm(size_weight)
        if num is not None:
            return num
    return None


def read_package_metrics(
    attributes: dict[str, Any],
) -> tuple[int | None, int | None, int | None, int | None]:
    """读取包裹尺寸/重量。未手改时用统一尺寸；手改后若和重量对不上，仍回落到统一尺寸。"""
    if force_package_metrics_enabled() and not package_is_manual(attributes):
        return get_fixed_package_metrics()
    depth, width, height = _parse_dimensions_from_attributes(attributes)
    weight = _parse_weight_grams(attributes)
    if force_package_metrics_enabled() and not _package_metrics_usable(depth, width, height, weight):
        return get_fixed_package_metrics()
    return depth, width, height, weight


def _is_explicit_package_key(key: str) -> bool:
    """只有明确的包装尺寸字段才能覆盖长宽高，商品特征里的「85 厘米」不行。"""
    text = str(key)
    if _is_net_product_key(text):
        return False
    lower = text.lower()
    if any(unit in lower for unit in ("см", "cm", "厘米")) and not any(
        unit in lower for unit in ("мм", "mm", "毫米")
    ):
        return False
    return any(
        alias in lower
        for alias in (
            "размер",
            "size",
            "尺寸",
            "длина",
            "ширина",
            "высота",
            "length",
            "width",
            "height",
            "depth",
            "габарит",
        )
    )


def _package_metrics_usable(
    depth: int | None,
    width: int | None,
    height: int | None,
    weight: int | None,
) -> bool:
    if not depth or not width or not height or not weight:
        return False
    return _package_density_issue(int(depth), int(width), int(height), int(weight)) is None


def _variant_explicit_package(
    variant_attributes: dict[str, Any] | None,
) -> tuple[int | None, int | None, int | None, int | None]:
    """变体上显式写入的包装长宽高/重量（审核中心或修复脚本）。"""
    attrs = {
        str(k): v
        for k, v in (variant_attributes or {}).items()
        if v is not None and str(v).strip()
    }
    if not attrs:
        return None, None, None, None
    depth, width, height = _parse_dimensions_from_attributes(attrs)
    # 也认 depth_mm / width_mm / height_mm / weight_g
    depth = depth or _parse_dimension_mm(attrs.get("depth_mm") or attrs.get("length_mm"))
    width = width or _parse_dimension_mm(attrs.get("width_mm"))
    height = height or _parse_dimension_mm(attrs.get("height_mm"))
    weight = _parse_weight_grams(attrs)
    if weight is None:
        weight = _parse_dimension_mm(attrs.get("weight_g") or attrs.get("weight"))
    return depth, width, height, weight


def read_variant_package_metrics(
    edit_attributes: dict[str, Any],
    variant: dict[str, Any] | None = None,
) -> tuple[int | None, int | None, int | None, int | None]:
    """
    优先用变体自己的包装尺寸/重量；否则回落到商品级（或统一默认）。
    变体标题里的「85 см」和袖长这类特征不能写成包装毫米。
    """
    variant = variant or {}
    v_depth, v_width, v_height, v_weight = _variant_explicit_package(
        variant.get("variant_attributes") if isinstance(variant.get("variant_attributes"), dict) else {}
    )
    if v_depth and v_width and v_height and v_weight:
        return v_depth, v_width, v_height, v_weight

    if force_package_metrics_enabled() and not package_is_manual(edit_attributes):
        return get_fixed_package_metrics()

    base_depth, base_width, base_height, weight = read_package_metrics(edit_attributes or {})

    # 商品级手改/统一尺寸时，仍允许变体覆盖缺省轴
    if package_is_manual(edit_attributes) or force_package_metrics_enabled():
        return (
            v_depth or base_depth,
            v_width or base_width,
            v_height or base_height,
            v_weight or weight,
        )

    merged: dict[str, Any] = {}
    for key, value in (variant.get("variant_attributes") or {}).items():
        if value is None or not str(value).strip() or not _is_explicit_package_key(str(key)):
            continue
        merged[str(key)] = value

    p_depth, p_width, p_height = _parse_dimensions_from_attributes(merged)
    return (
        v_depth or p_depth or base_depth,
        v_width or p_width or base_width,
        v_height or p_height or base_height,
        v_weight or weight,
    )


def _package_density_issue(
    depth: int,
    width: int,
    height: int,
    weight: int,
    *,
    sku: str | None = None,
) -> dict[str, Any] | None:
    """
    Ozon 会校验尺寸与重量是否匹配。体积很大但重量极轻时会报：
    「尺寸或重量不正确：更正并重新加载产品。」
    """
    volume_cm3 = (depth * width * height) / 1000.0
    if volume_cm3 <= 0 or weight <= 0:
        return None
    # ~0.003 g/cm³：软包类宽松下限；再设绝对下限 50g
    min_weight = max(50, int((volume_cm3 * 0.003) + 0.999))
    if weight >= min_weight:
        return None
    prefix = f"变体 {sku} " if sku else ""
    return {
        "code": "UNREALISTIC_PACKAGE_METRICS",
        "severity": "error",
        "message": (
            f"{prefix}包裹尺寸与重量不合理：{depth}×{width}×{height} mm "
            f"（约 {int(volume_cm3)} cm³）配 {weight}g 过轻，"
            f"建议重量至少约 {min_weight}g，或把包装长宽高改成折叠后的真实尺寸。"
            f"否则 Ozon 会报「尺寸或重量不正确」。"
        ),
    }


def package_metrics_issues(
    attributes: dict[str, Any],
    variants: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """缺长宽高或重量、或尺寸重量明显不匹配时给出错误。"""
    usable = [v for v in (variants or []) if str(v.get("sku") or "").strip()]
    if usable:
        issues: list[dict[str, Any]] = []
        for variant in usable:
            sku = str(variant.get("sku") or "").strip()
            depth, width, height, weight = read_variant_package_metrics(attributes, variant)
            missing: list[str] = []
            if depth is None:
                missing.append("长度(mm)")
            if width is None:
                missing.append("宽度(mm)")
            if height is None:
                missing.append("高度(mm)")
            if weight is None:
                missing.append("重量(g)")
            if missing:
                issues.append(
                    {
                        "code": "MISSING_PACKAGE_METRICS",
                        "severity": "error",
                        "message": f"变体 {sku} 缺少包裹尺寸/重量：{'、'.join(missing)}，请在商品编辑中补齐",
                    }
                )
                continue
            density = _package_density_issue(
                int(depth), int(width), int(height), int(weight), sku=sku
            )
            if density:
                issues.append(density)
        return issues

    depth, width, height, weight = read_package_metrics(attributes)
    missing: list[str] = []
    if depth is None:
        missing.append("长度(mm)")
    if width is None:
        missing.append("宽度(mm)")
    if height is None:
        missing.append("高度(mm)")
    if weight is None:
        missing.append("重量(g)")
    if missing:
        return [
            {
                "code": "MISSING_PACKAGE_METRICS",
                "severity": "error",
                "message": (
                    f"缺少包裹信息：{'、'.join(missing)}。"
                    "请到商品编辑填写真实长宽高与重量后再生成 Listing（不会自动写死默认值）"
                ),
            }
        ]
    density = _package_density_issue(int(depth), int(width), int(height), int(weight))
    return [density] if density else []


def _as_int_id(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _build_no_brand_attribute() -> dict[str, Any]:
    attribute_id = _as_int_id(os.getenv("OZON_BRAND_ATTRIBUTE_ID", "85")) or 85
    dictionary_value_id = _as_int_id(os.getenv("OZON_NO_BRAND_DICTIONARY_VALUE_ID", "126745801"))
    if dictionary_value_id:
        return {
            "id": attribute_id,
            "values": [{"dictionary_value_id": dictionary_value_id}],
        }
    return {
        "id": attribute_id,
        "values": [{"value": "Нет бренда"}],
    }


def _composed_description(edit: dict[str, Any]) -> str:
    description_parts = [edit.get("description") or ""]
    bullet_points = edit.get("bullet_points") or []
    if bullet_points:
        description_parts.append("\n".join(f"• {point}" for point in bullet_points))
    return "\n\n".join(part.strip() for part in description_parts if part and str(part).strip())


def collect_listing_issues(edit: dict[str, Any]) -> list[dict[str, Any]]:
    """软校验上架 Listing，返回 issues（error / warning）。"""
    issues: list[dict[str, Any]] = []
    attributes = edit.get("attributes") or {}

    if not str(edit.get("title") or "").strip():
        issues.append({"code": "MISSING_TITLE", "severity": "error", "message": "缺少标题"})
    if not _composed_description(edit):
        issues.append({"code": "MISSING_DESCRIPTION", "severity": "warning", "message": "描述为空，建议补充"})

    # 每个变体是独立 listing：各自需要 1 主图 + 4 附图
    required_images = 5
    variants = edit.get("variants") or []
    product_images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
    if variants:
        for variant in variants:
            sku = str(variant.get("sku") or "").strip() or "?"
            own = _variant_own_images(variant)
            # 旧数据尚未写入变体图集时，暂用商品级图兜底计数
            count = len(own) if own else len(product_images)
            if count < required_images:
                issues.append(
                    {
                        "code": "INSUFFICIENT_IMAGES",
                        "severity": "error",
                        "message": (
                            f"变体 {sku} 图片不足：该 listing 需要 1 张主图 + 4 张附图"
                            f"（共 {required_images} 张），当前 {count} 张"
                        ),
                    }
                )
    elif len(product_images) < required_images:
        issues.append(
            {
                "code": "INSUFFICIENT_IMAGES",
                "severity": "error",
                "message": (
                    f"图片不足：需要 1 张主图 + 4 张附图（共 {required_images} 张），"
                    f"当前仅 {len(product_images)} 张。请在商品编辑中补齐后再推送"
                ),
            }
        )

    description_category_id = _as_int_id(
        attributes.get("description_category_id") or attributes.get("category_id")
    )
    type_id = _as_int_id(attributes.get("type_id"))
    if description_category_id is None:
        issues.append(
            {
                "code": "MISSING_CATEGORY_ID",
                "severity": "error",
                "message": "缺少 description_category_id；打开编辑或生成 Listing 时会自动获取（需配置 OZON_COOKIE）",
            }
        )
    if type_id is None:
        issues.append(
            {
                "code": "MISSING_TYPE_ID",
                "severity": "error",
                "message": "缺少 type_id；打开编辑或生成 Listing 时会自动获取（需配置 OZON_COOKIE）",
            }
        )

    usable = 0
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        usable += 1
        if variant.get("price") is None:
            issues.append(
                {
                    "code": "MISSING_PRICE",
                    "severity": "error",
                    "message": f"变体 {sku} 缺少价格",
                }
            )
    if usable == 0:
        issues.append({"code": "MISSING_SKU", "severity": "error", "message": "没有可发布的 SKU 变体"})

    if not _as_int_id(os.getenv("OZON_WAREHOUSE_ID")):
        issues.append(
            {
                "code": "MISSING_WAREHOUSE",
                "severity": "error",
                "message": "未配置 OZON_WAREHOUSE_ID，真实发布无法推送 rFBS 库存，商品会显示库存不足",
            }
        )

    issues.extend(package_metrics_issues(attributes, edit.get("variants") or []))
    # 双区分项：颜色×尺码组合必须唯一，且两侧都要有值
    from services.ozon_attribute_fill import (
        detect_variant_aspect_mode,
        enrich_variant_aspect_fields,
        listing_color_label,
        listing_size_label,
        normalize_variant_aspect,
    )

    def _pair_key(value: str) -> str:
        return re.sub(r"\s+", "", str(value or "").strip().lower())

    aspect_mode = normalize_variant_aspect(attributes.get("variant_aspect"))
    detected = detect_variant_aspect_mode(variants)
    if detected == "both" and aspect_mode == "size":
        issues.append(
            {
                "code": "DUAL_ASPECT_MODE",
                "severity": "warning",
                "message": "变体同时存在多种颜色与尺码，已建议使用「颜色+尺码」双区分；当前为纯尺码轴可能丢颜色",
            }
        )
    seen_pairs: dict[tuple[str, str], str] = {}
    for variant in variants:
        sku = str(variant.get("sku") or "").strip() or "?"
        va = enrich_variant_aspect_fields(variant.get("variant_attributes") or {})
        # 优先用已写入的俄文区分字段（含 чехол 等后缀），避免 listing_* 把区分信息压扁导致误报撞车
        color = str(va.get("Название цвета") or va.get("颜色") or "").strip()
        if not color or any("\u4e00" <= ch <= "\u9fff" for ch in color):
            color = (
                listing_color_label(va.get("颜色"), va.get("Цвет"), va.get("Название цвета"), variant.get("title"))
                or str(va.get("颜色") or "").strip()
            )
        size = str(va.get("Размер") or va.get("尺码") or "").strip()
        if not size or any("\u4e00" <= ch <= "\u9fff" for ch in size):
            size = listing_size_label(
                va.get("尺码"),
                va.get("Размер"),
                va.get("规格"),
                va.get("区分项"),
                variant.get("title"),
            )
        if detected == "both" or aspect_mode == "both":
            if not color:
                issues.append(
                    {
                        "code": "MISSING_VARIANT_COLOR",
                        "severity": "error",
                        "message": f"双区分项变体 {sku} 缺少颜色/款式",
                    }
                )
            if not size:
                issues.append(
                    {
                        "code": "MISSING_VARIANT_SIZE",
                        "severity": "error",
                        "message": f"双区分项变体 {sku} 缺少尺码/阶数（如 3 ступени）",
                    }
                )
        pair = (_pair_key(color), _pair_key(size))
        if color or size:
            prev = seen_pairs.get(pair)
            if prev:
                issues.append(
                    {
                        "code": "DUPLICATE_ASPECT_PAIR",
                        "severity": "error",
                        "message": (
                            f"变体 {sku} 与 {prev} 的颜色+尺码组合重复"
                            f"（{color or '-'} / {size or '-'}），合卡会被 Ozon 拒绝"
                        ),
                    }
                )
            else:
                seen_pairs[pair] = sku

    missing_attrs = str(attributes.get("missing_required_attributes") or "").strip()
    if missing_attrs:
        issues.append(
            {
                "code": "MISSING_REQUIRED_ATTRIBUTES",
                "severity": "warning",
                "message": f"仍有必填属性未自动填齐：{missing_attrs}",
            }
        )
    return issues


def build_listing_summary(edit: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    attributes = edit.get("attributes") or {}
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
    return {
        "title": edit.get("title"),
        "description": edit.get("description"),
        "bullet_points": edit.get("bullet_points") or [],
        "images": images,
        "description_category_id": attributes.get("description_category_id") or attributes.get("category_id"),
        "type_id": attributes.get("type_id"),
        "fulfillment": attributes.get("fulfillment") or "rFBS",
        "brand_mode": attributes.get("brand_mode") or "no_brand",
        "attributes": attributes,
        "variants": [
            {
                "sku": variant.get("sku"),
                "title": variant.get("title") or edit.get("title"),
                "price": variant.get("price"),
                "quantity": variant.get("quantity"),
                "image_url": variant.get("image_url"),
                "variant_attributes": variant.get("variant_attributes") or {},
            }
            for variant in (edit.get("variants") or [])
            if str(variant.get("sku") or "").strip()
        ],
        "payload_offer_ids": [item.get("offer_id") for item in (items or [])],
        "payload_item_count": len(items or []),
    }


def _normalize_listing_image_url(url: str) -> str:
    text = str(url or "").strip()
    if "/wc140/" in text:
        text = text.replace("/wc140/", "/wc1200/")
    return text


def _variant_own_images(variant: dict[str, Any]) -> list[str]:
    """该变体自己的 listing 图集：主图 + 副图，不含商品级共用图。"""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        url = _normalize_listing_image_url(str(raw or ""))
        if not url or url in seen:
            return
        lower = url.lower()
        if lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            return
        seen.add(url)
        ordered.append(url)

    va = variant.get("variant_attributes") if isinstance(variant.get("variant_attributes"), dict) else {}
    _add(variant.get("image_url"))
    for key in ("image", "image_url", "主图"):
        _add(va.get(key))
    extra = va.get("images")
    if isinstance(extra, list):
        for item in extra:
            _add(item)
    return ordered[:15]


def _build_variant_listing_images(variant: dict[str, Any], fallback_images: list[str] | None = None) -> list[str]:
    """
    每个变体对应一个独立 listing：只用自己的主图+副图。
    旧数据若尚未写入变体图集，才回退到商品级 images。
    """
    ordered = _variant_own_images(variant)
    if ordered:
        return ordered
    fallback: list[str] = []
    seen: set[str] = set()
    for raw in fallback_images or []:
        url = _normalize_listing_image_url(str(raw or ""))
        if not url or url in seen:
            continue
        lower = url.lower()
        if lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            continue
        seen.add(url)
        fallback.append(url)
    return fallback[:15]


def _prefer_reachable_listing_images(urls: list[str]) -> list[str]:
    """清洗上架图片，保持传入顺序。"""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        url = _normalize_listing_image_url(str(raw or ""))
        if not url:
            continue
        lower = url.lower()
        if lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            continue
        if url in seen:
            continue
        seen.add(url)
        cleaned.append(url)
    return cleaned[:15]


def _colors_for_merged_card(
    variants: list[dict[str, Any]],
    attributes: dict[str, Any],
    edit: dict[str, Any],
) -> dict[str, str]:
    """合卡颜色：字典用基础色，冲突花色写出区分名。尺码走 Размеры, мм。"""
    from services.ozon_attribute_fill import (
        disambiguate_variant_colors,
        listing_color_label,
        listing_size_label,
    )

    if str(attributes.get("variant_aspect") or "") == "size":
        return {}
    size_by_sku: dict[str, str] = {}
    pending: list[tuple[str, str, str]] = []
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        from services.ozon_attribute_fill import enrich_variant_aspect_fields

        va = enrich_variant_aspect_fields(variant.get("variant_attributes") or {})
        blob = str(
            va.get("Цвет товара")
            or va.get("Цвет")
            or va.get("Название цвета")
            or va.get("颜色")
            or va.get("区分项")
            or va.get("规格")
            or ""
        ).strip()
        color = listing_color_label(
            blob,
            variant.get("title"),
            variant.get("url"),
            edit.get("title"),
        )
        size = listing_size_label(
            va.get("Размер"),
            va.get("尺码"),
            va.get("规格"),
            va.get("区分项"),
            blob,
            variant.get("title"),
        )
        if size:
            size_by_sku[sku] = size
        if not color:
            text_blob = " ".join(
                str(x or "")
                for x in (variant.get("title"), edit.get("title"), attributes.get("Материал"))
            ).lower()
            if any(token in text_blob for token in ("брезент", "tarpaulin", "canvas", "утеплен")):
                color = "серый"
        hint = str(
            va.get("颜色")
            or va.get("规格")
            or va.get("区分项")
            or variant.get("title")
            or ""
        )
        pending.append((sku, color, hint))

    # 仅当「同色 + 同尺码」撞车时才加花色区分；不同尺码可共用同一基础色
    from collections import defaultdict

    by_color_size: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)
    for sku, color, hint in pending:
        size_key = size_by_sku.get(sku) or ""
        by_color_size[(str(color or "").strip().lower(), size_key)].append((sku, color, hint))

    resolved: dict[str, str] = {}
    collide_rows: list[tuple[str, str, str]] = []
    for (_color_key, _size_key), rows in by_color_size.items():
        if len(rows) == 1:
            sku, color, _hint = rows[0]
            resolved[sku] = color
        else:
            collide_rows.extend(rows)

    if collide_rows:
        resolved.update(disambiguate_variant_colors(collide_rows))
    return resolved


def _size_mm_for_merged_card(
    variants: list[dict[str, Any]],
    *,
    height_mm: int = 80,
) -> dict[str, str]:
    """每个变体写入 Размеры, мм 的唯一毫米尺寸。"""
    from services.ozon_attribute_fill import enrich_variant_aspect_fields, listing_aspect_size_mm

    out: dict[str, str] = {}
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        va = enrich_variant_aspect_fields(variant.get("variant_attributes") or {})
        mm = listing_aspect_size_mm(
            va.get("Размер"),
            va.get("尺码"),
            va.get("规格"),
            va.get("区分项"),
            va.get("颜色"),
            variant.get("title"),
            height_mm=height_mm,
        )
        if mm:
            out[sku] = mm
    return out


def build_import_items(
    edit: dict[str, Any],
    *,
    warnings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    attributes = dict(edit.get("attributes") or {})
    # 合卡型号拼 external_id，避免与店铺内其它商品撞名
    external = str(edit.get("family_external_id") or attributes.get("external_id") or "").strip()
    if external:
        attributes.setdefault("family_external_id", external)
        # 若旧数据已写入过短型号，强制带上货号后缀
        model_key = "Название модели (для объединения в одну карточку)"
        old_model = str(attributes.get(model_key) or attributes.get("Название модели") or "").strip()
        if old_model and external not in old_model and "-" + external not in old_model:
            attributes[model_key] = f"{old_model}-{external}"[:80]

    description_category_id = _as_int_id(
        attributes.get("description_category_id") or attributes.get("category_id")
    )
    type_id = _as_int_id(attributes.get("type_id"))
    if description_category_id is None or type_id is None:
        raise OzonSellerError(
            "缺少 description_category_id 或 type_id，请配置 OZON_COOKIE 后自动获取"
        )

    # 纠正「名称是躺垫、类型却是狗窝」这类错配，否则 Ozon 报 Неверный тип
    from services.ozon_category_tree import (
        find_category_id_for_type,
        find_type_name,
        suggest_type_id_from_text,
    )

    title_blob = " ".join(
        [
            str(edit.get("title") or ""),
            str(attributes.get("Тип") or ""),
            *[
                str((v.get("title") or ""))
                + " "
                + str((v.get("variant_attributes") or {}).get("规格") or "")
                + " "
                + str((v.get("variant_attributes") or {}).get("颜色") or "")
                for v in (edit.get("variants") or [])[:8]
            ],
        ]
    )
    suggested_type = suggest_type_id_from_text(title_blob, current_type_id=type_id)
    if suggested_type and suggested_type != type_id:
        type_id = suggested_type
        attributes["type_id"] = str(suggested_type)
        attributes["Тип"] = find_type_name(suggested_type) or attributes.get("Тип")
        corrected_cat = find_category_id_for_type(suggested_type)
        if corrected_cat:
            description_category_id = int(corrected_cat)
            attributes["description_category_id"] = str(corrected_cat)
            attributes["category_id"] = str(corrected_cat)
    type_name = find_type_name(type_id) or str(attributes.get("Тип") or "")

    variants = [v for v in (edit.get("variants") or []) if str(v.get("sku") or "").strip()]
    package_errors = package_metrics_issues(attributes, variants)
    if package_errors:
        raise OzonSellerError(str(package_errors[0]["message"]))

    description = _composed_description(edit)

    vat = str(os.getenv("OZON_VAT", "0") or "0").strip() or "0"
    currency_code = (os.getenv("OZON_CURRENCY_CODE") or "CNY").strip() or "CNY"

    from services.ozon_attribute_fill import (
        apply_variant_distinguishing_attributes,
        build_ozon_attribute_values,
        contains_cjk,
        detect_variant_aspect_mode,
        enrich_variant_aspect_fields,
        listing_size_label,
        normalize_variant_aspect,
        strip_cjk,
    )

    # 双区分项：矩阵两侧都有差异时强制 both，避免只交颜色导致阶数/尺码丢失
    aspect_mode = normalize_variant_aspect(attributes.get("variant_aspect"))
    detected_aspect = detect_variant_aspect_mode(variants)
    if detected_aspect == "both" and aspect_mode != "both":
        aspect_mode = "both"
    attributes["variant_aspect"] = aspect_mode

    ozon_attrs, missing_required = build_ozon_attribute_values(
        description_category_id=description_category_id,
        type_id=type_id,
        edit_attributes=attributes,
        edit_title=str(edit.get("title") or ""),
        edit_description=description,
        variants=list(edit.get("variants") or []),
    )
    # 属性填充可能按官方树校正了类目
    corrected_category = _as_int_id(
        attributes.get("description_category_id") or attributes.get("category_id")
    )
    if corrected_category is not None:
        description_category_id = corrected_category
    if not ozon_attrs:
        ozon_attrs = [_build_no_brand_attribute()]
    if missing_required and warnings is not None:
        from services.ozon_attribute_fill import format_missing_attribute_labels

        msg = format_missing_attribute_labels(missing_required)
        first_code = str(missing_required[0].get("code") or "MISSING_REQUIRED_ATTRIBUTES")
        warnings.append(
            {
                "code": first_code,
                "severity": "warning",
                "message": (
                    msg
                    if first_code == "ATTRIBUTE_SCHEMA_FETCH_FAILED"
                    else f"仍有必填属性未自动填齐：{msg}"
                ),
            }
        )

    items: list[dict[str, Any]] = []
    fallback_images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
    color_by_sku = _colors_for_merged_card(variants, attributes, edit)
    size_mm_by_sku = _size_mm_for_merged_card(variants)
    # 多变体合卡：每个 offer 仍是独立 listing，图集互不共用
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        price = variant.get("price")
        if price is None:
            raise OzonSellerError(f"变体 {sku} 缺少价格，请先填写价格后再发布")
        depth, width, height, weight = read_variant_package_metrics(attributes, variant)
        # 兴远：尺寸优先选档，重量至少抬到渠道下限（避免物流不可选）
        if depth and width and height and weight:
            from services.xingyuan_freight import FreightError, normalize_package_for_shipping

            try:
                normalized = normalize_package_for_shipping(int(depth), int(width), int(height), float(weight))
                depth = int(normalized["depth_mm"])
                width = int(normalized["width_mm"])
                height = int(normalized["height_mm"])
                weight = int(normalized["weight_g"])
            except FreightError:
                pass
        item_images = _build_variant_listing_images(variant, fallback_images)
        # 把变体尺寸/重量写入区分属性（供 Ozon 特征表展示）
        va = enrich_variant_aspect_fields(variant.get("variant_attributes") or {})
        # 包裹尺寸只进包装字段/顶层 depth，不要写进可变特性「Размеры, мм」
        if depth is not None and width is not None and height is not None:
            va["Размер упаковки (Длина х Ширина х Высота), см"] = (
                f"{max(1, round(depth / 10))}x{max(1, round(width / 10))}x{max(1, round(height / 10))}"
            )
        aspect_mm = size_mm_by_sku.get(sku) or ""
        size_label = listing_size_label(
            va.get("Размер"),
            va.get("尺码"),
            va.get("规格"),
            va.get("区分项"),
            variant.get("title"),
        )
        if size_label:
            va["Размер"] = size_label
            va["尺码"] = size_label
            va["Размер товара"] = size_label
        if aspect_mm:
            va["Размеры, мм"] = aspect_mm
            va["Размеры товара, мм"] = aspect_mm
        else:
            net_depth, net_width, net_height = read_net_product_mm(va)
            if not (net_depth and net_width and net_height):
                net_depth, net_width, net_height = read_net_product_mm(attributes)
            if net_depth and net_width and net_height:
                net_text = f"{net_depth}*{net_width}*{net_height}"
                va["Размеры, мм"] = net_text
                va["Размеры товара, мм"] = net_text
        if weight is not None:
            va.setdefault("Вес товара, г", str(int(weight)))
            va.setdefault("Вес с упаковкой, г", str(int(weight)))
        # 纯尺码轴才去掉颜色；both/color 都保留颜色
        if aspect_mode == "size":
            for key in ("Цвет", "Цвет товара", "Название цвета"):
                va.pop(key, None)
        else:
            color = color_by_sku.get(sku) or ""
            if color:
                from services.ozon_attribute_fill import infer_color_label, listing_color_label

                # 字典色用基础色；Название цвета 用带花色的区分名，避免同尺寸多花色撞车
                base = infer_color_label(color) or listing_color_label(color) or color.split()[0]
                va["Цвет"] = base
                va["Цвет товара"] = base
                va["Название цвета"] = color
        variant_attrs = apply_variant_distinguishing_attributes(
            ozon_attrs,
            description_category_id=description_category_id,
            type_id=type_id,
            variant_attributes=va,
            edit_title=str(variant.get("title") or edit.get("title") or ""),
            variant_aspect=aspect_mode,
        )
        price_num = float(price)
        old_price_num = round(price_num * 1.3, 2)
        if float(old_price_num).is_integer():
            old_price_str = str(int(old_price_num))
        else:
            old_price_str = str(old_price_num)
        price_str = str(int(price_num) if float(price_num).is_integer() else price_num)
        va_for_name = dict(variant.get("variant_attributes") or {})
        size_hint = str(
            va_for_name.get("规格")
            or va_for_name.get("Размер")
            or va_for_name.get("尺码")
            or aspect_mm
            or ""
        )
        name = build_ozon_item_name(
            variant_title=str(variant.get("title") or ""),
            edit_title=str(edit.get("title") or ""),
            color=str(
                color_by_sku.get(sku)
                or va_for_name.get("Название цвета")
                or va_for_name.get("Цвет товара")
                or va_for_name.get("Цвет")
                or ""
            ),
            size_hint=size_hint,
            type_name=type_name,
        )
        item_description = strip_cjk(description) if contains_cjk(description) else description
        if contains_cjk(item_description) or not str(item_description or "").strip():
            item_description = strip_cjk(edit.get("description") or "") or str(
                edit.get("description") or ""
            )
        if contains_cjk(item_description):
            item_description = str(edit.get("title") or name)
        item: dict[str, Any] = {
            "offer_id": sku,
            "name": name,
            "description": item_description,
            "description_category_id": description_category_id,
            "type_id": type_id,
            "price": price_str,
            "old_price": old_price_str,
            "vat": vat,
            "currency_code": currency_code,
            "attributes": variant_attrs,
            "images": item_images,
            "depth": depth,
            "width": width,
            "height": height,
            "dimension_unit": "mm",
            "weight": weight,
            "weight_unit": "g",
        }
        if item_images:
            item["primary_image"] = item_images[0]
        items.append(item)

    if not items:
        raise OzonSellerError("没有可发布的 SKU 变体")
    return items


def preview_listing(edit: dict[str, Any]) -> dict[str, Any]:
    issues = collect_listing_issues(edit)
    errors = [item for item in issues if item.get("severity") == "error"]
    items: list[dict[str, Any]] | None = None
    stocks: list[dict[str, Any]] | None = None
    build_error: str | None = None

    if not errors:
        try:
            build_warnings: list[dict[str, Any]] = []
            items = build_import_items(edit, warnings=build_warnings)
            issues.extend(build_warnings)
            warehouse_id = _as_int_id(os.getenv("OZON_WAREHOUSE_ID"))
            if warehouse_id:
                stocks = build_stock_items(edit, warehouse_id)
        except OzonSellerError as exc:
            build_error = str(exc)
            issues.append({"code": "BUILD_FAILED", "severity": "error", "message": build_error})
            errors.append(issues[-1])

    return {
        "ok": not errors and items is not None,
        "issues": issues,
        "summary": build_listing_summary(edit, items),
        "payload_items": items or [],
        "stock_items": stocks or [],
        "build_error": build_error,
    }

def build_stock_items(edit: dict[str, Any], warehouse_id: int) -> list[dict[str, Any]]:
    from services.ozon_pricing_service import DEFAULT_STOCK_QTY

    try:
        default_qty = int((os.getenv("OZON_DEFAULT_STOCK_QTY") or str(DEFAULT_STOCK_QTY)).strip())
    except ValueError:
        default_qty = DEFAULT_STOCK_QTY
    if default_qty < 1:
        default_qty = DEFAULT_STOCK_QTY

    stocks: list[dict[str, Any]] = []
    for variant in edit.get("variants") or []:
        sku = str(variant.get("sku") or "").strip()
        if not sku:
            continue
        try:
            quantity = int(variant.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0
        # 0/空会推成「库存不足」；统一回落到默认上架库存
        if quantity < 1:
            quantity = default_qty
        stocks.append(
            {
                "offer_id": sku,
                "stock": quantity,
                "warehouse_id": warehouse_id,
            }
        )
    return stocks
