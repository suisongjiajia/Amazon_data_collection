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


def apply_fixed_package_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """把统一尺寸/重量写入 attributes（覆盖原值）。"""
    attrs = dict(attributes or {})
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
        return int(float(match.group(1).replace(",", ".")))
    except ValueError:
        return None


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
    if len(nums) == 1:
        return nums[0], nums[0], nums[0]
    return None, None, None


def _parse_dimensions_from_attributes(attributes: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    depth = None
    width = None
    height = None
    for key, value in attributes.items():
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
    """读取包裹尺寸/重量；开启强制模式时一律返回统一尺寸。"""
    if force_package_metrics_enabled():
        return get_fixed_package_metrics()
    depth, width, height = _parse_dimensions_from_attributes(attributes)
    weight = _parse_weight_grams(attributes)
    return depth, width, height, weight


def read_variant_package_metrics(
    edit_attributes: dict[str, Any],
    variant: dict[str, Any] | None = None,
) -> tuple[int | None, int | None, int | None, int | None]:
    """
    优先用变体自身规格（如 Размеры, мм）覆盖包裹长宽高；重量仍取编辑属性。
    强制模式下所有变体统一尺寸。
    """
    if force_package_metrics_enabled():
        return get_fixed_package_metrics()
    base_depth, base_width, base_height, weight = read_package_metrics(edit_attributes or {})
    variant = variant or {}
    merged: dict[str, Any] = {}
    for key, value in (variant.get("variant_attributes") or {}).items():
        if value is not None and str(value).strip():
            merged[str(key)] = value
    # 变体标题里偶发带尺寸时也可兜底
    title = variant.get("title")
    if title and not any("размер" in str(k).lower() for k in merged):
        merged.setdefault("size", title)

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
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]

    if not str(edit.get("title") or "").strip():
        issues.append({"code": "MISSING_TITLE", "severity": "error", "message": "缺少标题"})
    if not _composed_description(edit):
        issues.append({"code": "MISSING_DESCRIPTION", "severity": "warning", "message": "描述为空，建议补充"})

    # 强制：1 张主图 + 4 张附图，否则不可生成 Listing / 不可推送
    required_images = 5
    if len(images) < required_images:
        issues.append(
            {
                "code": "INSUFFICIENT_IMAGES",
                "severity": "error",
                "message": (
                    f"图片不足：需要 1 张主图 + 4 张附图（共 {required_images} 张），"
                    f"当前仅 {len(images)} 张。请在商品编辑中补齐后再推送"
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

    variants = edit.get("variants") or []
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


def _build_shared_listing_images(edit: dict[str, Any], base_images: list[str]) -> list[str]:
    """
    多变体共用同一套完整图库。
    Ozon 合卡后每个尺码/SKU 各自展示 images；若只给某个变体 1 张封面，
    切换尺码就会只剩一张图。
    """
    pool: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        url = _normalize_listing_image_url(str(raw or ""))
        if not url or url in seen:
            return
        lower = url.lower()
        if lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx")):
            return
        seen.add(url)
        pool.append(url)

    for url in base_images:
        _add(url)
    for variant in edit.get("variants") or []:
        _add(variant.get("image_url"))
        va = variant.get("variant_attributes") if isinstance(variant.get("variant_attributes"), dict) else {}
        for key in ("image", "image_url", "主图"):
            _add(va.get(key))

    return _prefer_reachable_listing_images(pool)[:15]


def _prefer_reachable_listing_images(urls: list[str]) -> list[str]:
    """
    清洗上架图片：
    - 去掉 PDF 等非图片链接（易触发「根据链接找不到文件」）
    - 放大 wc140 缩略图
    - 已转存 OSS 的完整图库优先保留（勿因 1 张变体 Ozon CDN 封面丢掉整库）
    - 否则再优先 Ozon CDN，并保留其余链接
    """
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

    oss = [u for u in cleaned if "aliyuncs.com" in u.lower()]
    ozon_cdn = [
        u
        for u in cleaned
        if ("ozon" in u.lower() or "ozone.ru" in u.lower() or "ozonusercontent" in u.lower())
        and "aliyuncs.com" not in u.lower()
    ]
    # 转存后图库通常 ≥5 张 OSS：整库保留，变体 Ozon 封面仅作补充
    if len(oss) >= 5:
        rest = [u for u in cleaned if u not in oss]
        return (oss + rest)[:15]
    if ozon_cdn:
        rest = [u for u in cleaned if u not in ozon_cdn]
        return (ozon_cdn + rest)[:15]
    return cleaned[:15]


def build_import_items(
    edit: dict[str, Any],
    *,
    warnings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    images = [url for url in (edit.get("images") or []) if isinstance(url, str) and url.strip()]
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
        infer_color_label,
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
    # 所有尺码/SKU 共用完整图库，避免合卡后切换变体只剩一张图
    shared_images = _build_shared_listing_images(edit, images)
    # 多变体合卡：共用型号名；颜色/尺码与包裹尺寸按变体覆盖
    for variant in variants:
        sku = str(variant.get("sku") or "").strip()
        price = variant.get("price")
        if price is None:
            raise OzonSellerError(f"变体 {sku} 缺少价格，请先填写价格后再发布")
        depth, width, height, weight = read_variant_package_metrics(attributes, variant)
        item_images = list(shared_images)
        variant_image = _normalize_listing_image_url(str(variant.get("image_url") or ""))
        # 仅调整主图顺序：变体封面若已在图库中则置顶；绝不把整库替换成单张封面
        if variant_image and variant_image in item_images:
            item_images = [variant_image] + [u for u in item_images if u != variant_image]
        elif variant_image and len(item_images) < 5:
            item_images = [variant_image] + item_images
            item_images = item_images[:15]
        # 把变体尺寸/重量写入区分属性（供 Ozon 特征表展示）
        va = dict(variant.get("variant_attributes") or {})
        if depth is not None and width is not None and height is not None:
            va.setdefault("Размеры, мм", f"{depth}*{width}*{height}")
            va["Размер упаковки (Длина х Ширина х Высота), см"] = (
                f"{max(1, round(depth / 10))}x{max(1, round(width / 10))}x{max(1, round(height / 10))}"
            )
        if weight is not None:
            va.setdefault("Вес товара, г", str(int(weight)))
            va.setdefault("Вес с упаковкой, г", str(int(weight)))
        # 优先保留变体已有颜色；否则从标题/链接推断；帆布类默认灰色
        junk_colors = {"уточняйте у продавца", "ask seller", "зеленый", "зелёный", ""}
        existing_color = str(
            va.get("Цвет товара") or va.get("Цвет") or va.get("Название цвета") or ""
        ).strip()
        color = existing_color if existing_color.lower() not in junk_colors else ""
        if not color:
            color = infer_color_label(
                variant.get("title"),
                variant.get("url"),
            ) or ""
        if not color:
            blob = " ".join(
                str(x or "")
                for x in (
                    variant.get("title"),
                    edit.get("title"),
                    attributes.get("Материал"),
                )
            ).lower()
            if any(x in blob for x in ("брезент", "tarpaulin", "canvas", "утеплен")):
                color = "серый"
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
        )
        price_num = float(price)
        old_price_num = round(price_num * 1.2, 2)
        if float(old_price_num).is_integer():
            old_price_str = str(int(old_price_num))
        else:
            old_price_str = str(old_price_num)
        price_str = str(int(price_num) if float(price_num).is_integer() else price_num)
        item: dict[str, Any] = {
            "offer_id": sku,
            "name": str(variant.get("title") or edit.get("title") or sku),
            "description": description,
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
