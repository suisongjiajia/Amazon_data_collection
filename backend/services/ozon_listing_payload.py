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
    raw = (os.getenv("OZON_FORCE_PACKAGE_METRICS") or "true").strip().lower()
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


def read_variant_package_metrics(
    edit_attributes: dict[str, Any],
    variant: dict[str, Any] | None = None,
) -> tuple[int | None, int | None, int | None, int | None]:
    """
    包裹尺寸以编辑属性为准。
    变体标题里的「85 см」和袖长这类特征不能写成包装毫米。
    """
    if force_package_metrics_enabled() and not package_is_manual(edit_attributes):
        return get_fixed_package_metrics()
    base_depth, base_width, base_height, weight = read_package_metrics(edit_attributes or {})
    if package_is_manual(edit_attributes) or force_package_metrics_enabled():
        return base_depth, base_width, base_height, weight

    variant = variant or {}
    merged: dict[str, Any] = {}
    for key, value in (variant.get("variant_attributes") or {}).items():
        if value is None or not str(value).strip() or not _is_explicit_package_key(str(key)):
            continue
        merged[str(key)] = value

    v_depth, v_width, v_height = _parse_dimensions_from_attributes(merged)
    return (
        v_depth or base_depth,
        v_width or base_width,
        v_height or base_height,
        weight,
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
    """合卡前先算每个变体的颜色。同色时用标题里独有的规格分开，避免可变特性完全一样。"""
    from services.ozon_attribute_fill import disambiguate_variant_colors, listing_color_label

    if str(attributes.get("variant_aspect") or "") == "size":
        return {}
    pending: list[tuple[str, str, str]] = []
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        va = variant.get("variant_attributes") or {}
        existing_color = str(
            va.get("Цвет товара") or va.get("Цвет") or va.get("Название цвета") or ""
        ).strip()
        color = listing_color_label(
            existing_color,
            variant.get("title"),
            variant.get("url"),
            edit.get("title"),
        )
        if not color:
            blob = " ".join(
                str(x or "")
                for x in (
                    variant.get("title"),
                    edit.get("title"),
                    attributes.get("Материал"),
                )
            ).lower()
            if any(token in blob for token in ("брезент", "tarpaulin", "canvas", "утеплен")):
                color = "серый"
        pending.append((sku, color, str(variant.get("title") or "")))
    return disambiguate_variant_colors(pending)


def build_import_items(
    edit: dict[str, Any],
    *,
    warnings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    attributes = edit.get("attributes") or {}

    description_category_id = _as_int_id(
        attributes.get("description_category_id") or attributes.get("category_id")
    )
    type_id = _as_int_id(attributes.get("type_id"))
    if description_category_id is None or type_id is None:
        raise OzonSellerError(
            "缺少 description_category_id 或 type_id，请配置 OZON_COOKIE 后自动获取"
        )

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
        strip_cjk,
    )

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
    # 多变体合卡：每个 offer 仍是独立 listing，图集互不共用
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        price = variant.get("price")
        if price is None:
            raise OzonSellerError(f"变体 {sku} 缺少价格，请先填写价格后再发布")
        depth, width, height, weight = read_variant_package_metrics(attributes, variant)
        item_images = _build_variant_listing_images(variant, fallback_images)
        # 把变体尺寸/重量写入区分属性（供 Ozon 特征表展示）
        va = dict(variant.get("variant_attributes") or {})
        if depth is not None and width is not None and height is not None:
            va.setdefault("Размеры, мм", f"{depth}*{width}*{height}")
            va["Размер упаковки (Длина х Ширина х Высота), см"] = (
                f"{max(1, round(depth / 10))}x{max(1, round(width / 10))}x{max(1, round(height / 10))}"
            )
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
        if str(attributes.get("variant_aspect") or "") == "size":
            for key in ("Цвет", "Цвет товара", "Название цвета"):
                va.pop(key, None)
        else:
            color = color_by_sku.get(sku) or ""
            if color:
                va["Цвет"] = color
                va["Цвет товара"] = color
                va["Название цвета"] = color
        variant_attrs = apply_variant_distinguishing_attributes(
            ozon_attrs,
            description_category_id=description_category_id,
            type_id=type_id,
            variant_attributes=va,
            edit_title=str(variant.get("title") or edit.get("title") or ""),
            variant_aspect=str(attributes.get("variant_aspect") or "color"),
        )
        price_num = float(price)
        old_price_num = round(price_num * 1.3, 2)
        if float(old_price_num).is_integer():
            old_price_str = str(int(old_price_num))
        else:
            old_price_str = str(old_price_num)
        price_str = str(int(price_num) if float(price_num).is_integer() else price_num)
        name = strip_cjk(variant.get("title") or edit.get("title") or "") or sku
        item_description = strip_cjk(description) if contains_cjk(description) else description
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
