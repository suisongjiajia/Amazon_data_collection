from __future__ import annotations

import os
import re
from typing import Any

from integrations.ozon_seller.client import OzonSellerClient, OzonSellerError


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def contains_cjk(value: Any) -> bool:
    return bool(_CJK_RE.search(str(value or "")))


def strip_cjk(value: Any) -> str:
    text = _CJK_RE.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,，、/;；")


def _as_int(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_attribute_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        attrs = result.get("attributes") or result.get("result")
        if isinstance(attrs, list):
            return [item for item in attrs if isinstance(item, dict)]
    attrs = payload.get("attributes")
    if isinstance(attrs, list):
        return [item for item in attrs if isinstance(item, dict)]
    return []


def _parse_value_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        values = result.get("values") or result.get("result")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, dict)]
    return []


def fetch_category_attributes(description_category_id: int, type_id: int) -> list[dict[str, Any]]:
    client = OzonSellerClient()
    last_error: Exception | None = None
    for language in ("DEFAULT", "RU"):
        try:
            payload = client.get_description_category_attributes(
                description_category_id=description_category_id,
                type_id=type_id,
                language=language,
            )
            attrs = _parse_attribute_list(payload)
            if attrs:
                return attrs
            last_error = OzonSellerError(
                f"类目属性为空（description_category_id={description_category_id}, type_id={type_id}, language={language}）"
            )
        except OzonSellerError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    return []


def _tokenize_tokens(*texts: Any) -> list[str]:
    """从标题/类目提示拆出可用于字典搜索的词（优先较长俄文/拉丁片段）。"""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in texts:
        text = str(raw or "").strip()
        if not text:
            continue
        # 整句前缀
        for chunk in (text[:40], text):
            cleaned = re.sub(r"\s+", " ", chunk).strip(" .,;:/|-")
            if len(cleaned) >= 2 and cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                tokens.append(cleaned)
        parts = re.findall(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-]{1,}", text)
        for part in parts:
            low = part.lower()
            if low in seen or len(part) < 2:
                continue
            seen.add(low)
            tokens.append(part)
    # 长词优先，更易命中类型名
    tokens.sort(key=lambda t: (-len(t), t.lower()))
    return tokens[:12]


def _score_dict_candidate(query: str, candidate_value: str) -> int:
    q = _norm(query)
    v = _norm(candidate_value)
    if not q or not v:
        return 0
    if q == v:
        return 1000
    if q in v or v in q:
        return 800 + min(len(q), len(v))
    # 简单字符重叠
    overlap = len(set(q) & set(v))
    return overlap * 3


def pick_dictionary_value(
    *,
    client: OzonSellerClient,
    attribute_id: int,
    description_category_id: int,
    type_id: int,
    queries: list[str],
) -> dict[str, Any] | None:
    """
    自动挑选字典枚举：
    1) search 优先（含类型名），命中 id==type_id 立即采用
    2) 枚举首页 id == type_id
    3) 首页枚举用查询词打分
    """
    best: dict[str, Any] | None = None
    best_score = 0

    def consider(item: dict[str, Any], query: str, base: int = 0) -> None:
        nonlocal best, best_score
        vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
        label = str(item.get("value") or "").strip()
        if vid is None or not label:
            return
        score = base + _score_dict_candidate(query, label)
        if vid == type_id:
            score = max(score, 2000)
        if score > best_score:
            best_score = score
            best = {
                "dictionary_value_id": vid,
                "value": label,
                "source": "search" if base else "values_scan",
            }

    # 1) search（限制次数，避免拖慢生成 Listing）
    for query in queries[:6]:
        q = str(query or "").strip()
        if len(q) < 2:
            continue
        try:
            payload = client.search_attribute_values(
                attribute_id=attribute_id,
                description_category_id=description_category_id,
                type_id=type_id,
                value=q[:80],
                limit=20,
            )
        except OzonSellerError:
            continue
        for item in _parse_value_list(payload):
            consider(item, q, base=50)
            vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
            if vid == type_id:
                return {
                    "dictionary_value_id": vid,
                    "value": str(item.get("value") or ""),
                    "source": "search_type_id",
                }
        if best_score >= 800:
            return best

    # 2/3) 首页 values
    try:
        page = client.get_attribute_values(
            attribute_id=attribute_id,
            description_category_id=description_category_id,
            type_id=type_id,
            limit=100,
            last_value_id=0,
        )
        values = _parse_value_list(page)
    except OzonSellerError:
        values = []

    for item in values:
        vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
        if vid == type_id:
            return {
                "dictionary_value_id": vid,
                "value": str(item.get("value") or ""),
                "source": "type_id_match",
            }

    for query in queries[:4]:
        for item in values:
            consider(item, query, base=0)

    if best and best_score >= 20:
        return best
    return None


def _default_model_name(*, edit_title: str, edit_attributes: dict[str, Any], variants: list[dict[str, Any]]) -> str:
    explicit = (
        edit_attributes.get("model")
        or edit_attributes.get("модель")
        or edit_attributes.get("型号")
        or edit_attributes.get("Название модели")
    )
    if explicit and str(explicit).strip():
        return str(explicit).strip()[:80]

    sku = ""
    for variant in variants or []:
        sku = str(variant.get("sku") or "").strip()
        if sku:
            break
    title = str(edit_title or "").strip()
    if title:
        # 取标题前段作型号，去掉过长尾巴
        short = re.split(r"[|/]", title, maxsplit=1)[0].strip()
        short = re.sub(r"\s+", " ", short)[:60]
        if short:
            return short
    if sku:
        return sku[:50]
    return "Model-1"


_SKIP_AUTO_FILL_TOKENS = (
    "pdf",
    "видео",
    "video",
    "сертиф",
    "документ",
    "инструкц",
)


def should_skip_attr_auto_fill(attr_name: str) -> bool:
    """PDF/视频/证书等链接类属性勿自动填，否则易触发「链接找不到文件」。"""
    name = _norm(attr_name)
    return any(token in name for token in _SKIP_AUTO_FILL_TOKENS)


def _substring_key_matches(target: str, key: str) -> bool:
    """避免「Название」误匹配「Название файла PDF / Название цвета」。"""
    if not target or not key:
        return False
    if target == key:
        return True
    shorter, longer = (key, target) if len(key) <= len(target) else (target, key)
    if shorter not in longer:
        return False
    remainder = longer.replace(shorter, "", 1)
    blocked = ("pdf", "файл", "видео", "video", "ссылк", "url", "цвет", "сертиф", "документ")
    if any(token in remainder for token in blocked):
        return False
    # 剩余部分过长则视为不同字段
    return len(remainder) <= 6


def infer_color_label(*texts: Any) -> str | None:
    """从标题/URL/属性文本推断俄语颜色（用于纠正 AI 错填）。"""
    blob = _norm(" ".join(str(t or "") for t in texts))
    if not blob:
        return None
    # URL 拉丁转写优先
    latin_hints = (
        ("golub", "голубой"),
        ("blue", "голубой"),
        ("seryy", "серый"),
        ("seriy", "серый"),
        ("sery", "серый"),
        ("grey", "серый"),
        ("gray", "серый"),
        ("chern", "черный"),
        ("black", "черный"),
        ("belay", "белый"),
        ("beliy", "белый"),
        ("white", "белый"),
        ("zelen", "зеленый"),
        ("green", "зеленый"),
        ("korich", "коричневый"),
        ("brown", "коричневый"),
        ("bezhev", "бежевый"),
        ("rozov", "розовый"),
        ("oranz", "оранжевый"),
        ("krasn", "красный"),
        ("fiolet", "фиолетовый"),
        ("zhelt", "желтый"),
    )
    for needle, label in latin_hints:
        if needle in blob:
            return label
    cyr_hints = (
        ("голубой", "голубой"),
        ("синий", "синий"),
        ("серый", "серый"),
        ("чёрный", "черный"),
        ("черный", "черный"),
        ("белый", "белый"),
        ("зеленый", "зеленый"),
        ("зелёный", "зеленый"),
        ("коричневый", "коричневый"),
        ("бежевый", "бежевый"),
        ("розовый", "розовый"),
        ("красный", "красный"),
        ("желтый", "желтый"),
        ("жёлтый", "желтый"),
    )
    for needle, label in cyr_hints:
        if _norm(needle) in blob:
            return label
    return None


def listing_color_label(existing: Any, *hints: Any) -> str:
    """推送到 Ozon 的颜色必须是俄语。汉字规格说明不能当颜色提交。"""
    text = str(existing or "").strip()
    junk = {"уточняйте у продавца", "ask seller", "зеленый", "зелёный", ""}
    if text and not contains_cjk(text) and text.lower() not in junk:
        return text
    return infer_color_label(*hints) or ""


_COLOR_GLUE = {"и", "а", "или"}


def _title_words(title: str) -> list[str]:
    return re.findall(r"[0-9A-Za-zА-Яа-яЁё-]+", str(title or ""))


def variant_color_phrase(title: str, other_titles: list[str]) -> str:
    """标题里其它变体没有的规格。例如「и рожками」收成「с рожками」。"""
    mine = _title_words(title)
    others: set[str] = set()
    for item in other_titles:
        others.update(word.lower() for word in _title_words(item))
    extra_at = [
        index
        for index, word in enumerate(mine)
        if word.lower() not in others and word.lower() not in _COLOR_GLUE
    ]
    if not extra_at:
        return ""
    start = extra_at[0]
    extra_set = set(extra_at)
    words: list[str] = []
    index = start
    while index < len(mine) and (index in extra_set or mine[index].lower() in _COLOR_GLUE):
        if mine[index].lower() not in _COLOR_GLUE:
            words.append(mine[index])
        index += 1
    phrase = " ".join(words).strip()
    if phrase and start > 0 and mine[start - 1].lower() == "и":
        phrase = f"с {phrase}"
    return phrase


def disambiguate_variant_colors(rows: list[tuple[str, str, str]]) -> dict[str, str]:
    """同一张卡上颜色相同的变体，补上标题里独有的规格，否则 Ozon 拒绝合卡。"""
    buckets: dict[str, list[tuple[str, str, str]]] = {}
    for sku, color, title in rows:
        buckets.setdefault(color.strip().lower(), []).append((sku, color.strip(), str(title or "")))
    resolved: dict[str, str] = {}
    for group in buckets.values():
        if len(group) < 2:
            sku, color, _title = group[0]
            resolved[sku] = color
            continue
        used: set[str] = set()
        for index, (sku, color, title) in enumerate(group):
            others = [item_title for other_index, (_sku, _color, item_title) in enumerate(group) if other_index != index]
            phrase = variant_color_phrase(title, others)
            label = f"{color} {phrase}".strip() if phrase else color
            if not label or label.lower() in used:
                label = f"{label} {sku}".strip()
            used.add(label.lower())
            resolved[sku] = label
    return resolved


def _find_source_value(attr_name: str, source_map: dict[str, str]) -> str | None:
    target = _norm(attr_name)
    if not target:
        return None
    if should_skip_attr_auto_fill(attr_name):
        return None
    if target in source_map:
        return source_map[target]
    for key, value in source_map.items():
        if not value:
            continue
        if _substring_key_matches(target, key):
            return value
    aliases = {
        "бренд": ["brand", "品牌", "бренд"],
        "модель": ["model", "型号", "модель", "названиемодели"],
        "цвет": ["color", "цвет", "颜色"],
        "материал": ["material", "материал", "材质"],
        "тип": ["type", "тип", "类型"],
        "предназначено": ["предназначено", "专为", "适用", "для"],
        "наполнитель": ["наполнитель", "填充", "filler", "保温"],
        "аннотац": ["аннотац", "简介", "summary", "annotation"],
        "хештег": ["хештег", "hashtag", "主题标签", "search_keywords", "tags"],
        "объединить": ["объединить", "组合成", "merge", "похожие"],
        "особенност": ["особенност", "设计特点", "feature"],
        "единицводном": ["единицводном", "一个商品中的件数", "units"],
        "количествотоварав": ["количествотоварав", "统一计量", "уеи"],
        "вес товара": ["вестовара", "商品重量", "weight_g", "вес,г"],
        "вес с упаковкой": ["вессупаковкой", "包装重量"],
        "упаковка": ["упаковка", "包装", "packaging"],
        "комплектац": ["комплектац", "配套", "комплект"],
        "заводских": ["заводских", "原厂包装"],
        "срок годности": ["срокгодности", "保质期"],
        "маркиров": ["маркиров", "标记代码", "marking"],
        "страна": ["страна", "原产国", "country", "china", "китай"],
        "размер упаковки": ["размерупаковки", "包装尺寸", "package size"],
        "размеры": ["размеры", "尺寸", "size"],
    }
    for canonical, keys in aliases.items():
        if any(k in target for k in keys) or canonical.replace(" ", "") in target.replace(" ", ""):
            # 颜色别名不要命中「Название цвета」以外的「Название*」纯标题字段
            for key, value in source_map.items():
                if should_skip_attr_auto_fill(key):
                    continue
                if any(a in key for a in keys) or canonical.replace(" ", "") in key.replace(" ", ""):
                    if value and value.strip().lower() not in {
                        "уточняйте у продавца",
                        "ask seller",
                        "нет",
                        "n/a",
                    }:
                        return value
    return None


def _listing_kit(current: Any, description: str) -> str:
    """配套写成「物品 — 数量」清单。太短的「A, B」会拆开，不再只留两个词。"""
    text = str(current or "").strip()
    if text.count("\n") >= 2 or len(text) >= 80:
        return text
    parts = [part.strip(" .") for part in re.split(r"[,;，、]", text) if part.strip(" .")]
    if len(parts) >= 2:
        return "\n".join(f"{part} — 1 шт." for part in parts)
    bullets: list[str] = []
    for line in (description or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith(("•", "-", "–")):
            continue
        item = stripped.lstrip("•-–").strip()
        if item:
            bullets.append(item)
    if bullets:
        return "\n".join(f"{item} — 1 шт." for item in bullets[:8])
    if text:
        return f"{text} — 1 шт."
    return "Домик для животных — 1 шт."


def _heuristic_attr_value(
    attr_name: str,
    *,
    edit_attributes: dict[str, Any],
    edit_title: str,
    description: str = "",
) -> str | None:
    """内容评分相关可选属性的兜底值（有明确合理默认时才填）。"""
    name = _norm(attr_name)
    weight = (
        edit_attributes.get("Вес, г")
        or edit_attributes.get("weight_g")
        or edit_attributes.get("Вес товара, г")
        or edit_attributes.get("weight")
    )
    weight_text = str(weight).strip() if weight is not None else ""
    if weight_text:
        weight_num = re.sub(r"[^\d]", "", weight_text)
    else:
        weight_num = ""

    depth = edit_attributes.get("Длина, мм") or edit_attributes.get("depth_mm")
    width = edit_attributes.get("Ширина, мм") or edit_attributes.get("width_mm")
    height = edit_attributes.get("Высота, мм") or edit_attributes.get("height_mm")

    def _mm_to_cm_pack() -> str | None:
        try:
            d = int(float(str(depth).replace(",", ".")))
            w = int(float(str(width).replace(",", ".")))
            h = int(float(str(height).replace(",", ".")))
        except (TypeError, ValueError):
            return None
        return f"{max(1, round(d / 10))}x{max(1, round(w / 10))}x{max(1, round(h / 10))}"

    if "вестовара" in name or name == "вестовара,г":
        return weight_num or None
    if "вессупаковкой" in name:
        return weight_num or None
    if "единицводномтоваре" in name or ("единиц" in name and "одном" in name):
        return "1"
    if "количествотоварав" in name or "уеи" in name:
        return "1"
    if "заводских" in name:
        return "1"
    if "страна" in name:
        return "Китай"
    if "маркиров" in name:
        return "false"
    if "аннотац" in name:
        text = (description or edit_attributes.get("Аннотация") or edit_title or "").strip()
        return text[:5000] if text else None
    if "хештег" in name:
        tags = edit_attributes.get("search_keywords") or edit_attributes.get("#Хештеги")
        formatted = format_ozon_hashtags(tags if tags else edit_title)
        return formatted or None
    if "объединить" in name and "похож" in name:
        return _default_model_name(
            edit_title=edit_title,
            edit_attributes=edit_attributes,
            variants=[],
        )
    if "наполнитель" in name:
        return str(
            edit_attributes.get("Наполнитель лежака/домика для животных")
            or edit_attributes.get("наполнитель")
            or "Синтепон"
        )
    if "упаковка" in name and "размер" not in name:
        return str(edit_attributes.get("Упаковка") or "Картонная коробка")
    if "комплектац" in name:
        return _listing_kit(edit_attributes.get("Комплектация"), description)
    if "особенност" in name:
        return str(
            edit_attributes.get("Особенности конструкции")
            or "Утеплённый уличный домик"
        )
    if "размерупаковки" in name or ("размер" in name and "упаков" in name):
        pack = edit_attributes.get("Размер упаковки (Длина х Ширина х Высота), см")
        if pack:
            return str(pack)
        return _mm_to_cm_pack()
    if name.startswith("размеры") or name == "размеры,мм":
        if depth and width and height:
            return f"{depth}*{width}*{height}"
        return None
    if "срокгодности" in name:
        return None
    return None


def _build_source_map(edit_attributes: dict[str, Any]) -> dict[str, str]:
    source: dict[str, str] = {}
    skip_keys = {
        "description_category_id",
        "type_id",
        "category_id",
        "brand_mode",
        "fulfillment",
        "pricing_formula",
        "freight_channel",
        "freight_cny",
        "pricing_error",
        "category_resolve_error",
        "missing_required_attributes",
        "image_rehost_error",
        "search_keywords",
        "currency_code",
        "ozon_auto_attributes",
        "listing_notes",
        "last_heal_errors",
        "heal_attempts",
        "package_manual",
        "variant_aspect",
    }
    for key, value in (edit_attributes or {}).items():
        if key in skip_keys or value is None:
            continue
        text = str(value).strip()
        if not text or contains_cjk(text):
            continue
        source[_norm(key)] = text
    return source


def format_ozon_hashtags(value: Any, *, limit: int = 12) -> str:
    """
    Ozon #Хештеги：每个标签以 # 开头，仅字母数字与下划线，标签之间用空格分隔。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    stop = {
        "для",
        "и",
        "на",
        "с",
        "по",
        "из",
        "к",
        "у",
        "о",
        "от",
        "the",
        "for",
        "and",
        "of",
        "a",
        "to",
    }
    raw_parts = re.split(r"[\s,;，、]+", text)
    tags: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        token = str(part or "").strip()
        if not token:
            continue
        token = token.lstrip("#")
        token = re.sub(r"[^\w]+", "_", token, flags=re.UNICODE)
        token = re.sub(r"_+", "_", token).strip("_")
        if len(token) < 3:
            continue
        if token.lower() in stop:
            continue
        token = token[:30]
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(f"#{token}")
        if len(tags) >= limit:
            break
    return " ".join(tags)


def _normalize_attr_value_for_type(attr_type: str, value: Any) -> str:
    """按 Ozon 属性类型规范化 value。

    Seller API 的 attributes.values[].value 是 string 字段：
    Boolean 传 \"true\"/\"false\"，数字也要转成字符串。
    """
    t = str(attr_type or "").strip().lower()
    if t == "boolean":
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "да", "是", "需要"}:
            return "true"
        return "false"
    if t in {"integer", "int"}:
        try:
            return str(int(float(str(value).replace(",", "."))))
        except (TypeError, ValueError):
            match = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
            if match:
                try:
                    return str(int(float(match.group(1).replace(",", "."))))
                except ValueError:
                    pass
            return str(value).strip()
    if t in {"decimal", "float", "number"}:
        try:
            num = float(str(value).replace(",", "."))
            return str(int(num)) if num.is_integer() else str(num)
        except (TypeError, ValueError):
            match = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
            if match:
                try:
                    num = float(match.group(1).replace(",", "."))
                    return str(int(num)) if num.is_integer() else str(num)
                except ValueError:
                    pass
            return str(value).strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        num = float(value)
        return str(int(num)) if num.is_integer() else str(num)
    return str(value).strip()


def _coerce_filled_value(attr: dict[str, Any], value: Any) -> str:
    attr_type = str(attr.get("type") or "")
    name = str(attr.get("name") or attr.get("description") or "")
    if "хештег" in _norm(name):
        return format_ozon_hashtags(value)
    text = _normalize_attr_value_for_type(attr_type, value)
    if contains_cjk(text):
        text = strip_cjk(text)
    return text


def format_missing_attribute_labels(items: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for item in items:
        text = str(item.get("message") or item.get("name") or "").strip()
        if text:
            labels.append(text)
    return "; ".join(labels[:12])


def build_ozon_attribute_values(
    *,
    description_category_id: int,
    type_id: int,
    edit_attributes: dict[str, Any],
    edit_title: str = "",
    edit_description: str = "",
    variants: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    返回 (可提交 attributes[], warnings[])
    会尽量自动选择字典枚举与型号文本；可选属性也会用 AI/启发式补齐以提升内容评分。
    """
    from services.ozon_category_tree import find_category_id_for_type, find_type_name

    category_id = description_category_id
    try:
        schema = fetch_category_attributes(category_id, type_id)
    except OzonSellerError as first_exc:
        corrected = find_category_id_for_type(type_id)
        if corrected and corrected != category_id:
            try:
                schema = fetch_category_attributes(corrected, type_id)
                category_id = corrected
                edit_attributes["description_category_id"] = str(corrected)
            except OzonSellerError as second_exc:
                return [], [
                    {
                        "id": None,
                        "code": "ATTRIBUTE_SCHEMA_FETCH_FAILED",
                        "name": "类目属性接口",
                        "message": f"拉取类目属性失败: {second_exc}",
                    }
                ]
        else:
            return [], [
                {
                    "id": None,
                    "code": "ATTRIBUTE_SCHEMA_FETCH_FAILED",
                    "name": "类目属性接口",
                    "message": f"拉取类目属性失败: {first_exc}",
                }
            ]

    brand_attr_id = _as_int(os.getenv("OZON_BRAND_ATTRIBUTE_ID", "85")) or 85
    no_brand_dict_id = _as_int(os.getenv("OZON_NO_BRAND_DICTIONARY_VALUE_ID", "126745801"))
    source_map = _build_source_map(edit_attributes)
    variants = variants or []
    description = str(edit_description or edit_attributes.get("Аннотация") or "").strip()

    type_name = find_type_name(type_id) or str(edit_attributes.get("type_name") or "")
    search_queries = _tokenize_tokens(
        type_name,
        edit_title,
        edit_attributes.get("category_hint"),
        *[str(v.get("title") or "") for v in variants[:3]],
    )

    client = OzonSellerClient()
    auto_notes: list[str] = []

    filled: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    filled.append(
        {
            "id": brand_attr_id,
            "values": (
                [{"dictionary_value_id": no_brand_dict_id}]
                if no_brand_dict_id
                else [{"value": "Нет бренда"}]
            ),
        }
    )
    seen_ids.add(brand_attr_id)

    for attr in schema:
        attr_id = _as_int(attr.get("id") or attr.get("attribute_id"))
        if attr_id is None or attr_id in seen_ids:
            continue
        name = str(attr.get("name") or attr.get("description") or f"attr-{attr_id}")
        is_required = bool(attr.get("is_required") or attr.get("required"))
        if attr_id == brand_attr_id or _norm(name) in {"бренд", "brand", "品牌"}:
            continue
        # 绝不自动填写 PDF/视频链接类字段（空链接会触发卖家后台警告）
        if should_skip_attr_auto_fill(name):
            continue

        dictionary_id = attr.get("dictionary_id")
        has_dictionary = bool(_as_int(dictionary_id))
        source_value = _find_source_value(name, source_map)
        if not source_value:
            source_value = _heuristic_attr_value(
                name,
                edit_attributes=edit_attributes,
                edit_title=edit_title,
                description=description,
            )
        name_norm = _norm(name)
        if "аннотац" in name_norm:
            rich = str(description or "").strip()
            if rich:
                source_value = rich[:5000]
        elif "комплектац" in name_norm:
            source_value = _listing_kit(source_value, description)
        if source_value and contains_cjk(source_value):
            cleaned = strip_cjk(source_value)
            source_value = cleaned or None
        is_model_attr = any(k in name_norm for k in ("модел", "model", "型号", "названиемодели"))

        # 非必填且无来源/启发式：跳过
        if not is_required and not source_value and not is_model_attr:
            continue

        if not has_dictionary:
            value = source_value
            if not value and is_model_attr:
                value = _default_model_name(
                    edit_title=edit_title,
                    edit_attributes=edit_attributes,
                    variants=variants,
                )
                auto_notes.append(f"{name}={value}")
            if value is not None and str(value).strip() != "":
                coerced = _coerce_filled_value(attr, value)
                filled.append({"id": attr_id, "values": [{"value": coerced}]})
                seen_ids.add(attr_id)
                auto_notes.append(f"{name}={coerced}")
                continue
            if is_required:
                missing.append(
                    {
                        "id": attr_id,
                        "code": "MISSING_REQUIRED_ATTRIBUTE",
                        "name": name,
                        "dictionary_id": dictionary_id,
                        "message": name,
                    }
                )
            continue

        # 字典属性：自动搜索/匹配枚举
        queries = list(search_queries)
        if source_value:
            queries.insert(0, source_value)

        picked = pick_dictionary_value(
            client=client,
            attribute_id=attr_id,
            description_category_id=category_id,
            type_id=type_id,
            queries=queries,
        )
        if picked:
            filled.append(
                {
                    "id": attr_id,
                    "values": [{"dictionary_value_id": picked["dictionary_value_id"]}],
                }
            )
            seen_ids.add(attr_id)
            auto_notes.append(f"{name}={picked.get('value') or picked['dictionary_value_id']}")
            continue

        # 字典匹配失败时：部分内容属性允许退回纯文本（布尔除外）
        if source_value and not is_required and str(attr.get("type") or "").lower() != "boolean":
            coerced = _coerce_filled_value(attr, source_value)
            filled.append({"id": attr_id, "values": [{"value": coerced}]})
            seen_ids.add(attr_id)
            auto_notes.append(f"{name}={coerced}(text)")
            continue

        if is_required:
            missing.append(
                {
                    "id": attr_id,
                    "code": "MISSING_REQUIRED_ATTRIBUTE",
                    "name": name,
                    "dictionary_id": dictionary_id,
                    "message": f"{name}（字典属性，自动匹配失败）",
                }
            )

    if auto_notes:
        edit_attributes["ozon_auto_attributes"] = "; ".join(auto_notes[:20])

    return filled, missing


_VARIANT_ASPECT_ALIASES = (
    ("цвет", ("цвет", "color", "颜色", "colour")),
    (
        "размер",
        (
            "размер",
            "size",
            "尺码",
            "разм",
            "габарит",
            "рукав",
            "sleeve",
            "袖长",
            "袖",
        ),
    ),
    ("вес", ("вес", "weight", "重量", "масса")),
    ("память", ("память", "memory", "storage", "объем", "объём", "gb", "容量")),
    ("вкус", ("вкус", "flavor", "味")),
    ("комплектац", ("комплектац", "комплект", "package", "套装")),
)


def is_variant_aspect_attr_name(name: str) -> bool:
    norm = _norm(name)
    # 包装尺寸不是合卡可变特性，避免误覆盖
    if "упаков" in norm:
        return False
    for _canonical, keys in _VARIANT_ASPECT_ALIASES:
        if any(k in norm for k in keys):
            return True
    return False


def _is_color_aspect_name(name: str) -> bool:
    return any(token in _norm(name) for token in ("цвет", "color", "颜色", "colour"))


def _is_size_aspect_name(name: str) -> bool:
    if _is_color_aspect_name(name):
        return False
    norm = _norm(name)
    if "упаков" in norm:
        return False
    return any(
        token in norm
        for token in ("размер", "size", "尺码", "рукав", "sleeve", "袖", "габарит")
    ) or ("длина" in norm and "рукав" in norm)


def _aspect_source_from_overrides(attr_name: str, overrides: dict[str, str]) -> str | None:
    """按属性名从变体 overrides 取值。袖长类优先匹配 袖长/рукав，其次 Размер。"""
    mapped = {_norm(k): v for k, v in overrides.items()}
    source = _find_source_value(attr_name, mapped)
    if source:
        return source
    name_norm = _norm(attr_name)
    preferred_keys: tuple[str, ...]
    if any(token in name_norm for token in ("рукав", "sleeve", "袖")):
        preferred_keys = ("袖长", "рукав", "sleeve", "размер", "size", "尺码")
    elif _is_size_aspect_name(attr_name):
        preferred_keys = ("размер", "size", "尺码", "袖长", "рукав", "sleeve")
    elif _is_color_aspect_name(attr_name):
        preferred_keys = ("цвет", "color", "颜色", "названиецвета")
    else:
        preferred_keys = ()
    for key, value in overrides.items():
        key_norm = _norm(key)
        if any(token in key_norm for token in preferred_keys):
            return value
    for key, value in overrides.items():
        if is_variant_aspect_attr_name(key) and (
            any(part in name_norm for part in _norm(key).split() if len(part) > 2)
            or any(part in key_norm for part in name_norm.split() if len(part) > 2)
        ):
            return value
    return None


def apply_variant_distinguishing_attributes(
    base_attributes: list[dict[str, Any]],
    *,
    description_category_id: int,
    type_id: int,
    variant_attributes: dict[str, Any] | None,
    edit_title: str = "",
    variant_aspect: str | None = None,
) -> list[dict[str, Any]]:
    """
    在共享属性基础上，按变体规格覆盖颜色/尺码等区分属性。
    型号名等合卡字段保持与 base 一致。
    variant_aspect=size 时去掉颜色可变特性；=color 时按颜色覆盖。
    """
    aspect_mode = str(variant_aspect or "color").strip().lower()
    if aspect_mode not in {"color", "size"}:
        aspect_mode = "color"
    overrides = {
        str(k).strip(): str(v).strip()
        for k, v in (variant_attributes or {}).items()
        if str(k).strip() and str(v).strip()
    }

    try:
        schema = fetch_category_attributes(description_category_id, type_id)
    except OzonSellerError:
        return [dict(item) for item in base_attributes]

    client = OzonSellerClient()
    result = [dict(item) for item in base_attributes]
    by_id = {
        int(item["id"]): index
        for index, item in enumerate(result)
        if _as_int(item.get("id")) is not None
    }
    drop_ids: set[int] = set()

    for attr in schema:
        attr_id = _as_int(attr.get("id") or attr.get("attribute_id"))
        if attr_id is None:
            continue
        name = str(attr.get("name") or attr.get("description") or "")
        is_aspect = bool(attr.get("is_aspect"))
        if not is_aspect and not is_variant_aspect_attr_name(name):
            continue
        # 型号用于合卡，不能按变体改
        if any(k in _norm(name) for k in ("модел", "model", "型号", "названиемодели")):
            continue
        # 包装尺寸不是可变特性
        if "упаков" in _norm(name):
            continue

        is_color = _is_color_aspect_name(name)
        if aspect_mode == "size" and is_color:
            drop_ids.add(attr_id)
            continue
        if aspect_mode == "color" and _is_size_aspect_name(name) and not overrides:
            continue

        if not overrides:
            continue
        source_value = _aspect_source_from_overrides(name, overrides)
        if not source_value:
            continue
        if contains_cjk(source_value):
            if is_color:
                source_value = infer_color_label(edit_title) or ""
            else:
                source_value = strip_cjk(source_value)
        if not source_value or contains_cjk(source_value):
            continue

        dictionary_id = attr.get("dictionary_id")
        has_dictionary = bool(_as_int(dictionary_id))
        payload_value: dict[str, Any]
        if has_dictionary:
            picked = pick_dictionary_value(
                client=client,
                attribute_id=attr_id,
                description_category_id=description_category_id,
                type_id=type_id,
                queries=[source_value, edit_title],
            )
            if not picked:
                payload_value = {"value": _coerce_filled_value(attr, source_value)}
            else:
                payload_value = {"dictionary_value_id": picked["dictionary_value_id"]}
        else:
            payload_value = {"value": _coerce_filled_value(attr, source_value)}

        entry = {"id": attr_id, "values": [payload_value]}
        if attr_id in by_id:
            result[by_id[attr_id]] = entry
        else:
            by_id[attr_id] = len(result)
            result.append(entry)

    if drop_ids:
        result = [item for item in result if _as_int(item.get("id")) not in drop_ids]
    return result
