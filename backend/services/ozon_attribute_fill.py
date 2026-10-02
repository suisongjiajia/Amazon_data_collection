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


_CATEGORY_ATTR_CACHE: dict[tuple[int, int], list[dict[str, Any]]] = {}


def fetch_category_attributes(description_category_id: int, type_id: int) -> list[dict[str, Any]]:
    cache_key = (int(description_category_id), int(type_id))
    cached = _CATEGORY_ATTR_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]

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
                _CATEGORY_ATTR_CACHE[cache_key] = attrs
                return [dict(item) for item in attrs]
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


def _is_type_attr_name(name: str) -> bool:
    """仅「Тип」类属性才允许用 type_id 对齐字典项。"""
    norm = _norm(name)
    if not norm:
        return False
    if any(token in norm for token in ("типтовар", "типиздел", "типпродук")):
        return True
    return norm in {"тип", "type", "类型"} or norm.startswith("тип,") or norm.startswith("тип ")


def _is_shelf_life_attr(name: str) -> bool:
    norm = _norm(name)
    return "срокгодности" in norm or "保质期" in str(name or "")


def _is_filler_attr(name: str) -> bool:
    return "наполнитель" in _norm(name) or "填充" in str(name or "")


def _is_animal_size_attr(name: str) -> bool:
    """宠物尺寸字典（≠ 包装尺寸 / Размеры мм）。"""
    norm = _norm(name)
    if "упаков" in norm or "мм" in norm or ",mm" in norm:
        return False
    size_like = any(token in norm for token in ("размер", "size", "尺码", "габарит"))
    animal_like = any(
        token in norm
        for token in ("животн", "питомц", "pet", "собак", "кошк", "宠", "звер")
    )
    return size_like and animal_like


def _looks_like_cooling_or_hard_shell(*texts: Any) -> bool:
    blob = _norm(" ".join(str(t or "") for t in texts))
    return any(
        token in blob
        for token in (
            "охлажд",
            "ротанг",
            "rattan",
            "летн",
            "凉席",
            "降温",
            "藤席",
            "藤编",
            "cooling",
            "хладоэлемент",
        )
    )


def _pet_size_search_queries(*texts: Any) -> list[str]:
    """从规格/标题抽出可供宠物尺码字典搜索的词（S/M/L、до N кг）。"""
    queries: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = str(value or "").strip()
        if len(text) < 1:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        queries.append(text)

    for raw in texts:
        text = str(raw or "").strip()
        if not text:
            continue
        label = listing_size_label(text)
        if label:
            letter = re.match(r"^(XXL|XL|XS|S|M|L)\b", label, flags=re.I)
            if letter:
                add(letter.group(1).upper())
            add(label)
        jin = re.search(r"(\d+)\s*斤", text)
        if jin:
            kg = max(1, round(int(jin.group(1)) * 0.5))
            add(f"до {kg} кг")
            add(f"до {kg}кг")
        kg_match = re.search(r"(?:до|до\s+)?(\d+)\s*кг", text, flags=re.I)
        if kg_match:
            add(f"до {kg_match.group(1)} кг")
    return queries


_DICT_PICK_CACHE: dict[tuple[Any, ...], dict[str, Any] | None] = {}


def pick_dictionary_value(
    *,
    client: OzonSellerClient,
    attribute_id: int,
    description_category_id: int,
    type_id: int,
    queries: list[str],
    attribute_name: str = "",
) -> dict[str, Any] | None:
    """
    自动挑选字典枚举：
    1) search 优先；仅 Тип 属性允许 id==type_id 立即采用
    2) Тип 属性枚举首页 id == type_id
    3) 首页枚举用查询词打分（需达到阈值）
    """
    normalized_queries = tuple(
        str(q or "").strip() for q in queries[:6] if str(q or "").strip()
    )
    cache_key = (
        int(attribute_id),
        int(description_category_id),
        int(type_id),
        _norm(attribute_name),
        normalized_queries,
    )
    if cache_key in _DICT_PICK_CACHE:
        cached = _DICT_PICK_CACHE[cache_key]
        return dict(cached) if cached else None

    best: dict[str, Any] | None = None
    best_score = 0
    allow_type_id = _is_type_attr_name(attribute_name)

    def consider(item: dict[str, Any], query: str, base: int = 0) -> None:
        nonlocal best, best_score
        vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
        label = str(item.get("value") or "").strip()
        if vid is None or not label:
            return
        score = base + _score_dict_candidate(query, label)
        if allow_type_id and vid == type_id:
            score = max(score, 2000)
        if score > best_score:
            best_score = score
            best = {
                "dictionary_value_id": vid,
                "value": label,
                "source": "search" if base else "values_scan",
            }

    # 1) search（限制次数，避免拖慢生成 Listing）
    for query in normalized_queries:
        q = str(query or "").strip()
        if len(q) < 1:
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
            if allow_type_id and vid == type_id:
                result = {
                    "dictionary_value_id": vid,
                    "value": str(item.get("value") or ""),
                    "source": "search_type_id",
                }
                _DICT_PICK_CACHE[cache_key] = result
                return dict(result)
        if best_score >= 800:
            _DICT_PICK_CACHE[cache_key] = best
            return dict(best) if best else None

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

    if allow_type_id:
        for item in values:
            vid = _as_int(item.get("id") or item.get("dictionary_value_id"))
            if vid == type_id:
                result = {
                    "dictionary_value_id": vid,
                    "value": str(item.get("value") or ""),
                    "source": "type_id_match",
                }
                _DICT_PICK_CACHE[cache_key] = result
                return dict(result)

    for query in normalized_queries[:4]:
        for item in values:
            consider(item, query, base=0)

    if best and best_score >= 50:
        _DICT_PICK_CACHE[cache_key] = best
        return dict(best)
    _DICT_PICK_CACHE[cache_key] = None
    return None


def _default_model_name(*, edit_title: str, edit_attributes: dict[str, Any], variants: list[dict[str, Any]]) -> str:
    explicit = (
        edit_attributes.get("model")
        or edit_attributes.get("модель")
        or edit_attributes.get("型号")
        or edit_attributes.get("Название модели")
        or edit_attributes.get("Название модели (для объединения в одну карточку)")
    )
    if explicit and str(explicit).strip():
        return str(explicit).strip()[:80]

    external = str(
        edit_attributes.get("family_external_id")
        or edit_attributes.get("external_id")
        or edit_attributes.get("Артикул")
        or edit_attributes.get("Offer ID")
        or ""
    ).strip()

    sku = ""
    for variant in variants or []:
        sku = str(variant.get("sku") or "").strip()
        if sku:
            break
    title = str(edit_title or "").strip()
    short = ""
    if title:
        # 取标题前段作型号，去掉过长尾巴
        short = re.split(r"[|/]", title, maxsplit=1)[0].strip()
        short = re.sub(r"\s+", " ", short)[:50]
    # 合卡型号必须在店铺内尽量唯一，否则会撞上其它已上架卡
    suffix = external or (sku[-12:] if sku else "")
    if short and suffix:
        return f"{short}-{suffix}"[:80]
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
    # 中文颜色词（1688 规格常见）；先匹配复合色，再匹配单字，避免「黄绿」被「绿」抢走
    cjk_hints = (
        ("墨绿", "зеленый"),
        ("军绿", "зеленый"),
        ("清新绿", "зеленый"),
        ("黄绿", "жёлто-зелёный"),
        ("蓝黄", "сине-жёлтый"),
        ("深蓝", "синий"),
        ("浅蓝", "голубой"),
        ("深灰色", "тёмно-серый"),
        ("深灰", "тёмно-серый"),
        ("浅灰色", "светло-серый"),
        ("浅灰", "светло-серый"),
        ("黑白", "чёрно-белый"),
        ("灰色", "серый"),
        ("绿色", "зеленый"),
        ("蓝色", "синий"),
        ("黑色", "черный"),
        ("白色", "белый"),
        ("米色", "бежевый"),
        ("米黄", "бежевый"),
        ("粉色", "розовый"),
        ("棕色", "коричневый"),
        ("黄色", "желтый"),
        ("红色", "красный"),
        ("橙色", "оранжевый"),
        ("紫色", "фиолетовый"),
        ("卡其", "бежевый"),
        ("咖色", "коричневый"),
        ("咖啡", "коричневый"),
        ("绿", "зеленый"),
        ("蓝", "синий"),
        ("灰", "серый"),
        ("黑", "черный"),
        ("白", "белый"),
        ("粉", "розовый"),
        ("棕", "коричневый"),
        ("黄", "желтый"),
        ("红", "красный"),
        ("橙", "оранжевый"),
        ("紫", "фиолетовый"),
    )
    for needle, label in cjk_hints:
        if needle in "".join(str(t or "") for t in texts):
            return label
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
    # 复合色必须先于基础色，否则 тёмно-серый 会被「серый」子串抢走
    cyr_hints = (
        ("тёмно-серый", "тёмно-серый"),
        ("темно-серый", "тёмно-серый"),
        ("светло-серый", "светло-серый"),
        ("жёлто-зелёный", "жёлто-зелёный"),
        ("желто-зеленый", "жёлто-зелёный"),
        ("сине-жёлтый", "сине-жёлтый"),
        ("сине-желтый", "сине-жёлтый"),
        ("чёрно-белый", "чёрно-белый"),
        ("черно-белый", "чёрно-белый"),
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


def parse_packed_color_size(text: str) -> tuple[str, str]:
    """
    解析 1688 常见粘连规格，例如：
    - 灰色S(40*50)CM → (灰色, S 40x50)
    - 咖色XL(66*90)CM → (咖色, XL 66x90)
    - 清新绿 · L 60*50cm（建议15斤内） → (清新绿, L 60x50)
    """
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    # 灰色S(40*50)CM / 咖色M(48*60)CM
    matched = re.match(
        r"^([\u4e00-\u9fffA-Za-zА-Яа-яЁё]+?)\s*"
        r"(XXL|XL|XS|S|M|L|\d+)\s*"
        r"[\(（]\s*(\d+(?:[.,]\d+)?)\s*[*x×х]\s*(\d+(?:[.,]\d+)?)\s*[\)）]\s*"
        r"(?:CM|cm|см)?\s*$",
        raw,
        flags=re.I,
    )
    if matched:
        color = matched.group(1).strip()
        size_code = matched.group(2).upper()
        a = matched.group(3).replace(",", ".")
        b = matched.group(4).replace(",", ".")
        try:
            a_i, b_i = int(float(a)), int(float(b))
            dims = f"{a_i}x{b_i}"
        except ValueError:
            dims = f"{a}x{b}"
        return color, f"{size_code} {dims}"

    color = ""
    size = ""
    working = raw
    for sep in (" · ", " / ", "|"):
        if sep in working:
            left, right = working.split(sep, 1)
            color = left.strip()
            working = right.strip()
            break
    # 从右侧提取 S/M/L + 尺寸
    size_match = re.search(
        r"\b(XXL|XL|XS|S|M|L)\b\s*[^\d]*(\d+(?:[.,]\d+)?)\s*[*x×х]\s*(\d+(?:[.,]\d+)?)",
        working,
        flags=re.I,
    )
    if size_match:
        size_code = size_match.group(1).upper()
        a = size_match.group(2).replace(",", ".")
        b = size_match.group(3).replace(",", ".")
        try:
            dims = f"{int(float(a))}x{int(float(b))}"
        except ValueError:
            dims = f"{a}x{b}"
        size = f"{size_code} {dims}"
        if not color:
            color = working[: size_match.start()].strip(" -_,./")
    if not color and contains_cjk(raw):
        # 仅颜色中文
        color_only = re.sub(r"[A-Za-z0-9*x×х\(\)（）.\sCM]+$", "", raw, flags=re.I).strip()
        if color_only:
            color = color_only
    return color, size


def _steps_size_label(text: str) -> str:
    """阶数/层数类尺码：3层 / 三层 / 三阶 / 4 ступени → 3 ступени。"""
    raw = str(text or "").strip()
    if not raw:
        return ""
    m = re.search(
        r"(\d+)\s*(?:层|阶|级|档|ступен\w*|step\w*|ступ\.?)",
        raw,
        flags=re.I,
    )
    if m:
        n = int(m.group(1))
        if 1 <= n <= 30:
            return f"{n} ступени"
    # 中文数字：三层 / 三阶直角【高30CM】
    cn_map = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    m_cn = re.search(r"([一二两三四五六七八九十])\s*(?:层|阶)", raw)
    if m_cn:
        n = cn_map.get(m_cn.group(1))
        if n:
            return f"{n} ступени"
    return ""


def is_cover_aspect_text(*texts: Any) -> bool:
    blob = " ".join(str(t or "") for t in texts)
    if not blob:
        return False
    lower = blob.casefold()
    # 「不含填充物楼梯」是布套；「宠物楼梯/海绵」是楼梯本体
    if any(token in blob for token in ("不含填充", "不含楼梯", "换洗外套", "单独换洗", "布套")):
        return True
    if "外套" in blob and "楼梯" not in blob.replace("不含填充物楼梯", ""):
        return True
    return any(token in lower for token in ("чехол", "сменный"))


def is_stair_product_text(*texts: Any) -> bool:
    blob = " ".join(str(t or "") for t in texts)
    if not blob or is_cover_aspect_text(blob):
        return False
    return any(token in blob for token in ("海绵", "宠物楼梯", "填充物", "缓步楼梯"))


def listing_size_label(*texts: Any) -> str:
    """从变体规格提取俄语/拉丁尺码标签（去掉中文说明）。"""
    def _with_cover_prefix(source: str, steps: str) -> str:
        if is_cover_aspect_text(source):
            if "чехол" not in steps.casefold():
                return f"чехол {steps}"[:40]
        return steps[:40]

    for raw in texts:
        text = str(raw or "").strip()
        if not text:
            continue
        steps = _steps_size_label(text)
        if steps:
            return _with_cover_prefix(text, steps)
        _color, packed = parse_packed_color_size(text)
        if packed:
            return packed[:40]
        # 优先截取 · / 后的尺码段
        working = text
        for sep in (" · ", " / ", "|"):
            if sep in working:
                working = working.split(sep)[-1].strip()
                break
        steps = _steps_size_label(working)
        if steps:
            return _with_cover_prefix(text, steps)
        # 标题里的「S 40x50 см」
        title_match = re.search(
            r"\b(XXL|XL|XS|S|M|L)\b\s*[^\d]*(\d+(?:[.,]\d+)?)\s*[*x×х]\s*(\d+(?:[.,]\d+)?)",
            working,
            flags=re.I,
        )
        if title_match:
            a = title_match.group(2).replace(",", ".")
            b = title_match.group(3).replace(",", ".")
            try:
                dims = f"{int(float(a))}x{int(float(b))}"
            except ValueError:
                dims = f"{a}x{b}"
            return f"{title_match.group(1).upper()} {dims}"[:40]
        cleaned = strip_cjk(working)
        cleaned = re.sub(r"[（(][^）)]*[）)]", "", cleaned)
        cleaned = re.sub(r"[（）()\"'`]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_,.")
        # 避免把「【 30CM】」这类高度残片当尺码（阶数商品应走 ступени）
        if cleaned and re.fullmatch(r"[【\[]?\s*\d+\s*CM\s*[】\]]?", cleaned, flags=re.I):
            continue
        # 避免把整段俄语标题当成尺码
        if cleaned and len(cleaned) <= 24 and re.search(r"[A-Za-z0-9]", cleaned):
            return cleaned[:40]
    return ""


def normalize_variant_aspect(value: Any) -> str:
    """合卡区分轴：color | size | both（双区分项）。"""
    text = str(value or "").strip().lower().replace("-", "_").replace("+", "_")
    if text in {"both", "color_size", "dual", "multi", "color_and_size"}:
        return "both"
    if text == "size":
        return "size"
    return "color"


def enrich_variant_aspect_fields(variant_attributes: dict[str, Any] | None) -> dict[str, str]:
    """
    规范变体区分字段：拆开「款式 · 尺码」，补齐 颜色/尺码/Цвет/Размер。
    双轴商品必须两侧都有值，否则 Ozon 只能显示单区分。
    """
    raw = {
        str(k).strip(): str(v).strip()
        for k, v in (variant_attributes or {}).items()
        if str(k).strip() and str(v).strip()
    }
    color = str(
        raw.get("颜色")
        or raw.get("Цвет товара")
        or raw.get("Цвет")
        or raw.get("Название цвета")
        or raw.get("款式")
        or ""
    ).strip()
    size = str(
        raw.get("尺码")
        or raw.get("Размер")
        or raw.get("Размер товара")
        or raw.get("尺寸，毫米")
        or raw.get("Размеры, мм")
        or ""
    ).strip()
    packed_src = str(raw.get("区分项") or raw.get("规格") or color or "").strip()
    if packed_src:
        packed_color, packed_size = parse_packed_color_size(packed_src)
        if packed_color and not color:
            color = packed_color
        if packed_size and not size:
            size = packed_size
        steps = _steps_size_label(packed_src)
        if steps and not size:
            size = steps
        # 「蓝色 · 3层」：左侧颜色、右侧阶数
        if " · " in packed_src or " / " in packed_src:
            sep = " · " if " · " in packed_src else " / "
            left, right = packed_src.split(sep, 1)
            if left.strip() and (not color or color == packed_src):
                color = left.strip()
            right_size = listing_size_label(right) or _steps_size_label(right)
            if right_size and not size:
                size = right_size
    if not size:
        size = listing_size_label(
            raw.get("规格"),
            raw.get("区分项"),
            raw.get("Размер"),
            raw.get("尺码"),
        )
    # 颜色里若仍粘着尺码，拆开，避免双轴塌成单色
    if color:
        only_color, embedded_size = parse_packed_color_size(color)
        if only_color and embedded_size:
            color = only_color
            if not size:
                size = embedded_size
        color_steps = _steps_size_label(color)
        if color_steps and not size:
            size = color_steps
            color = re.sub(
                r"\s*[·/|]?\s*\d+\s*(?:层|阶|级|ступен\w*|step\w*)\s*",
                "",
                color,
                flags=re.I,
            ).strip(" ·/-")
    out = dict(raw)
    if color:
        out.setdefault("颜色", color)
        out.setdefault("款式", color.split(" · ")[0].strip() or color)
        out.setdefault("Цвет", color)
        out.setdefault("Цвет товара", color)
        out.setdefault("Название цвета", color)
    if size:
        out["尺码"] = size
        out["Размер"] = size
        out["Размер товара"] = size
        steps = _steps_size_label(size) or (size if "ступен" in size.lower() else "")
        if steps:
            # 布套必须保留 чехол，否则 enrich 后与同色楼梯的「N ступени」再次撞车
            if is_cover_aspect_text(size) or "чехол" in size.casefold():
                if "чехол" not in steps.casefold():
                    steps = f"чехол {steps}"
            out["Размер"] = steps
            out["尺码"] = steps
            out["Размер товара"] = steps
    return out


def detect_variant_aspect_mode(variants: list[dict[str, Any]] | None) -> str:
    """根据变体矩阵推断合卡轴：两侧都有差异 → both。"""
    colors: set[str] = set()
    sizes: set[str] = set()
    for variant in variants or []:
        va = enrich_variant_aspect_fields(variant.get("variant_attributes") or {})
        color = listing_color_label(
            va.get("颜色"),
            va.get("Цвет"),
            va.get("Название цвета"),
            variant.get("title"),
        ) or str(va.get("颜色") or va.get("Цвет") or "").strip()
        size = listing_size_label(
            va.get("尺码"),
            va.get("Размер"),
            va.get("规格"),
            va.get("区分项"),
            variant.get("title"),
        )
        if color:
            colors.add(_norm(color))
        if size:
            sizes.add(_norm(size))
    if len(colors) > 1 and len(sizes) > 1:
        return "both"
    if len(sizes) > 1 and len(colors) <= 1:
        return "size"
    return "color"

def _is_color_name_attr(name: str) -> bool:
    """Название цвета：自由文本区分项，可带花色短语。"""
    norm = _norm(name)
    return "названиецвета" in norm.replace(" ", "") or (
        "название" in norm and "цвет" in norm
    )


def _clean_color_display_name(value: str) -> str:
    """保留区分花色的俄语短语，只去掉中文和尾部尺码噪声。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if contains_cjk(text):
        text = strip_cjk(text)
    # 去掉尾部 S/M/L 与尺寸，尺码另有 Размеры, мм
    text = re.sub(
        r",?\s*(?:XXL|XL|XS|S|M|L)?\s*\d+(?:[.,]\d+)?\s*[x×х*]\s*\d+(?:[.,]\d+)?\s*(?:см|mm|мм)?\s*$",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b(XXL|XL|XS|S|M|L)\b", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip(" ,/-")
    return text[:80]


def _pattern_color_phrase_from_cjk(*texts: Any) -> str:
    """从 1688 花色文案抽出俄语区分短语（避免多种蓝都叫 синий）。"""
    blob = "".join(str(t or "") for t in texts)
    patterns = (
        ("招财猫", "с кошкой удачи"),
        ("福猫", "с кошкой удачи"),
        ("鲸鱼", "с китом"),
        ("粉灰蓝格子", "клетка"),
        ("黄色格子", "жёлтая клетка"),
        ("红底猫咪", "с кошкой"),
        ("白底福猫", "белый с кошкой"),
        ("粉底草莓", "с клубникой"),
        ("草莓", "с клубникой"),
        ("牛油果", "авокадо"),
        ("格子", "клетка"),
        ("猫咪", "с кошкой"),
    )
    for needle, phrase in patterns:
        if needle in blob:
            return phrase
    return ""


def listing_color_label(existing: Any, *hints: Any) -> str:
    """推送到 Ozon 的颜色必须是俄语。汉字规格说明不能当颜色提交。"""
    candidates = [existing, *hints]
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        packed_color, _size = parse_packed_color_size(text)
        if packed_color:
            inferred = infer_color_label(packed_color, text) or ""
            if inferred:
                return inferred
        junk = {"уточняйте у продавца", "ask seller", ""}
        # 已是短俄语颜色词时保留原文（含 ё/大小写），便于字典匹配
        if (
            text
            and not contains_cjk(text)
            and text.lower() not in junk
            and len(text) <= 20
            and " " not in text
            and not re.search(r"\d", text)
            and infer_color_label(text)
        ):
            return text
        inferred = infer_color_label(text) or ""
        if inferred:
            return inferred
    return infer_color_label(*candidates) or ""


def resolve_variant_aspect_pair(
    variant_attributes: dict[str, Any] | None,
    *,
    title: str = "",
) -> tuple[str, str]:
    """从规格/标题推出合卡用的 (颜色名, 尺码)，布套带 чехол 前缀避免与楼梯撞车。"""
    va = dict(variant_attributes or {})
    # 只用中文「规格」判断楼梯/布套；区分项可能已被写成带 чехол 的俄语
    spec_blob = str(va.get("规格") or "").strip()
    dist = str(va.get("区分项") or "")
    if contains_cjk(dist):
        spec_blob = f"{spec_blob} {dist}".strip()
    for key in ("颜色", "尺码"):
        raw = str(va.get(key) or "")
        if contains_cjk(raw):
            spec_blob = f"{spec_blob} {raw}".strip()
    title_text = str(title or "")
    if is_cover_aspect_text(spec_blob):
        cover = True
    elif is_stair_product_text(spec_blob):
        cover = False
    else:
        cover = is_cover_aspect_text(spec_blob, title_text) and not is_stair_product_text(
            spec_blob, title_text
        )
    color_hints = [spec_blob, title_text]
    for key in ("颜色", "Название цвета", "Цвет"):
        raw = str(va.get(key) or "")
        # 推断颜色时忽略已带 чехол 的旧标签，强制从规格重算
        if raw and "чехол" not in raw.casefold():
            color_hints.insert(0, raw)
    color = listing_color_label(*color_hints)
    size_hints = [spec_blob, title_text]
    for key in ("尺码", "Размер", "规格"):
        raw = str(va.get(key) or "")
        if raw and not (raw.casefold().startswith("чехол") and not contains_cjk(raw)):
            size_hints.insert(0, raw)
    size = listing_size_label(*size_hints)
    if cover:
        base = (color or "серый").strip()
        # 去掉旧后缀再统一加
        base = re.sub(r"\s*чехол(?:\s*\d+)?\s*$", "", base, flags=re.I).strip() or "серый"
        color = f"{base} чехол"
        if size and "чехол" not in size.casefold():
            size = f"чехол {size}"
    else:
        # 楼梯：清掉误加的 чехол
        if color:
            color = re.sub(r"\s*чехол(?:\s*\d+)?\s*$", "", color, flags=re.I).strip()
        if size:
            size = re.sub(r"^чехол\s+", "", size, flags=re.I).strip()
    return color, size


def apply_unique_aspect_labels_to_edit(edit: dict[str, Any]) -> int:
    """重写变体 Название цвета / Размер，消除 DUPLICATE_ASPECT_PAIR。返回改写条数。"""
    from db.ozon_workflow import update_product_edit, update_product_edit_variant

    variants = list(edit.get("variants") or [])
    if not variants:
        return 0

    planned: list[tuple[dict[str, Any], str, str]] = []
    seen: dict[tuple[str, str], int] = {}
    changed = 0

    for variant in variants:
        va = dict(variant.get("variant_attributes") or {})
        color, size = resolve_variant_aspect_pair(va, title=str(variant.get("title") or ""))
        if not color and not size:
            planned.append((variant, color, size))
            continue
        key = (re.sub(r"\s+", "", color.lower()), re.sub(r"\s+", "", size.lower()))
        hit = seen.get(key)
        if hit is None:
            seen[key] = 1
        else:
            seen[key] = hit + 1
            # 仍撞车：给颜色名加序号（极少见，兜底）
            color = f"{color} {seen[key]}".strip()
            key = (re.sub(r"\s+", "", color.lower()), re.sub(r"\s+", "", size.lower()))
            seen[key] = 1
        planned.append((variant, color, size))

    edit_id = int(edit["id"])
    for variant, color, size in planned:
        va = dict(variant.get("variant_attributes") or {})
        before = (
            str(va.get("Название цвета") or ""),
            str(va.get("Размер") or ""),
            str(va.get("颜色") or ""),
            str(va.get("尺码") or ""),
        )
        if color:
            base = color.split()[0]
            if color.startswith("тёмно-серый") or color.startswith("темно-серый"):
                base = "тёмно-серый"
            elif color.startswith("светло-серый"):
                base = "светло-серый"
            elif color.startswith("чёрно-белый") or color.startswith("черно-белый"):
                base = "чёрно-белый"
            va["颜色"] = color
            va["Цвет"] = base
            va["Цвет товара"] = base
            va["Название цвета"] = color
            va["款式"] = color
        if size:
            va["尺码"] = size
            va["Размер"] = size
            va["Размер товара"] = size
        if color and size:
            va["区分项"] = f"{color} · {size}"
        after = (
            str(va.get("Название цвета") or ""),
            str(va.get("Размер") or ""),
            str(va.get("颜色") or ""),
            str(va.get("尺码") or ""),
        )
        if after == before:
            continue
        vid = variant.get("id")
        if vid is None:
            continue
        update_product_edit_variant(int(vid), variant_attributes=va)
        changed += 1

    if changed:
        attrs = dict(edit.get("attributes") or {})
        attrs["variant_aspect"] = "both"
        update_product_edit(edit_id, attributes=attrs, clear_listing=True)
    return changed


def size_label_to_mm(size_label: str, *, height_mm: int = 80) -> str | None:
    """
    把 S 40x50 / 400*500 转成 Ozon 可变特性「Размеры, мм」格式。
    小于 200 的数字按厘米换算成毫米。
    """
    text = str(size_label or "").strip()
    if not text:
        return None
    matched = re.search(
        r"(\d+)\s*[x×х*]\s*(\d+)(?:\s*[x×х*]\s*(\d+))?",
        text,
        flags=re.I,
    )
    if not matched:
        return None
    a = int(float(matched.group(1).replace(",", ".")))
    b = int(float(matched.group(2).replace(",", ".")))
    c = int(float(matched.group(3).replace(",", "."))) if matched.group(3) else int(height_mm)
    if a < 200 and b < 200:
        a *= 10
        b *= 10
        if matched.group(3) is None:
            c = int(height_mm)
        elif c < 200:
            c *= 10
    return f"{a}*{b}*{c}"


def listing_aspect_color(*texts: Any) -> str:
    """合卡用的纯俄语颜色（必须能进 Ozon 颜色字典）。"""
    return listing_color_label(*texts)


def listing_aspect_size_mm(*texts: Any, height_mm: int = 80) -> str:
    """合卡用的尺寸毫米串，写入可变特性 Размеры, мм。"""
    size = listing_size_label(*texts)
    return size_label_to_mm(size, height_mm=height_mm) or ""


def _color_has_size_noise(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.search(r"(?:\b(?:XS|S|M|L|XL|XXL)\b|\d+\s*[xх*×]\s*\d+|\d+\s*cm|\d+\s*см)", text, re.I)
    ) or (" " in text and len(text.split()) >= 2)


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
    """同一张卡上颜色相同的变体，补上标题/花色独有短语，否则 Ozon 拒绝合卡。"""
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
            phrase = _pattern_color_phrase_from_cjk(title) or variant_color_phrase(title, others)
            # 去掉尺码噪声短语（尺码另有 Размеры, мм）
            if phrase and re.fullmatch(r"\d+(?:[x×х*]\d+)+", phrase.replace(" ", ""), flags=re.I):
                phrase = ""
            label = f"{color} {phrase}".strip() if phrase else color
            label = _clean_color_display_name(label) or color
            if not label or label.lower() in used:
                suffix = sku[-6:] if sku else str(index + 1)
                label = f"{color} вариант {suffix}".strip()
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
        explicit = (
            edit_attributes.get("Наполнитель лежака/домика для животных")
            or edit_attributes.get("наполнитель")
        )
        if explicit:
            return str(explicit)
        # 凉席不默认填；棉窝默认合成棉
        if _looks_like_cooling_or_hard_shell(edit_title, description, str(edit_attributes.get("Тип") or "")):
            return None
        return "Синтепон"
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
    非字典：启发式/编辑稿；字典：并行 API 候选 → 高分直用 → 歧义一次 AI 白名单选择。
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

    # 字典属性先收集再批量：并行拉候选 → 高分直用 → 歧义一次 AI 白名单选择
    from services.ozon_ai_dict_pick import DictAttrJob, resolve_dictionary_picks

    dict_jobs: list[DictAttrJob] = []
    dict_meta: dict[int, dict[str, Any]] = {}

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
        name_norm = _norm(name)

        # 非食品类目的「保质期」AI 常填过小天数，且会别名灌进多个同类字段 → 直接跳过
        if _is_shelf_life_attr(name):
            continue
        # 凉席/藤编/降温垫：不交填充物（「Без наполнителя」会被判 not fresh）
        if _is_filler_attr(name) and _looks_like_cooling_or_hard_shell(
            edit_title, description, str(edit_attributes.get("Тип") or "")
        ):
            continue
        # 薄垫默认不填；attributes 已给 Синтепон 等合法值时仍提交以覆盖旧脏值
        if _is_filler_attr(name):
            blob = _norm(
                " ".join(
                    [
                        edit_title,
                        description,
                        str(edit_attributes.get("Тип") or ""),
                        str(source_map.get("тип") or ""),
                    ]
                )
            )
            thin_mat = any(
                t in blob for t in ("мат", "подстилк", "коврик", "матрас", "полоск", "垫子", "睡垫", "凉席")
            )
            nested_house = any(t in blob for t in ("домик", "будка", "гнезд", "тоннел", "猫窝"))
            explicit_filler = str(
                edit_attributes.get("Наполнитель лежака/домика для животных")
                or edit_attributes.get("наполнитель")
                or ""
            ).strip()
            if thin_mat and not nested_house and not explicit_filler:
                continue

        source_value = _find_source_value(name, source_map)
        if not source_value:
            source_value = _heuristic_attr_value(
                name,
                edit_attributes=edit_attributes,
                edit_title=edit_title,
                description=description,
            )
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

        # 字典属性：收集 job，稍后批量 API+AI
        queries = list(search_queries)
        if source_value:
            queries.insert(0, str(source_value))
        if _is_animal_size_attr(name):
            variant_texts = [
                str((v.get("variant_attributes") or {}).get(k) or "")
                for v in variants
                for k in (v.get("variant_attributes") or {})
            ]
            for q in _pet_size_search_queries(edit_title, source_value, *variant_texts):
                if q not in queries:
                    queries.insert(0, q)
        if _is_filler_attr(name) and source_value:
            if source_value not in queries:
                queries.insert(0, str(source_value))

        dict_jobs.append(
            DictAttrJob(
                attribute_id=attr_id,
                name=name,
                is_required=is_required,
                queries=queries[:6],
                hint=str(source_value or ""),
            )
        )
        dict_meta[attr_id] = {
            "name": name,
            "dictionary_id": dictionary_id,
            "is_required": is_required,
        }

    if dict_jobs:
        product_context = {
            "title": edit_title,
            "type_id": type_id,
            "type_name": type_name,
            "description": (description or "")[:800],
            "hints": {
                str(j.attribute_id): (j.hint or "")[:80] for j in dict_jobs if j.hint
            },
        }
        picks = resolve_dictionary_picks(
            client=client,
            jobs=dict_jobs,
            description_category_id=category_id,
            type_id=type_id,
            product_context=product_context,
        )
        for job in dict_jobs:
            meta = dict_meta[job.attribute_id]
            picked = picks.get(job.attribute_id)
            if picked:
                filled.append(
                    {
                        "id": job.attribute_id,
                        "values": [{"dictionary_value_id": picked["dictionary_value_id"]}],
                    }
                )
                seen_ids.add(job.attribute_id)
                src = picked.get("source") or ""
                auto_notes.append(
                    f"{meta['name']}={picked.get('value') or picked['dictionary_value_id']}"
                    + (f"({src})" if src else "")
                )
                continue
            if meta["is_required"]:
                missing.append(
                    {
                        "id": job.attribute_id,
                        "code": "MISSING_REQUIRED_ATTRIBUTE",
                        "name": meta["name"],
                        "dictionary_id": meta["dictionary_id"],
                        "message": f"{meta['name']}（字典属性，自动匹配失败）",
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
    # 宠物尺寸字典不要误用包装尺寸 / 毫米尺寸
    if _is_animal_size_attr(attr_name):
        candidates = [
            v
            for k, v in overrides.items()
            if v
            and "упаков" not in _norm(k)
            and "мм" not in _norm(k)
            and "mm" not in _norm(k)
        ]
        pet_queries = _pet_size_search_queries(*candidates)
        if pet_queries:
            return pet_queries[0]
        for value in candidates:
            letter = re.search(r"\b(XXL|XL|XS|S|M|L)\b", value, flags=re.I)
            if letter:
                return letter.group(1).upper()
        return None

    # Название цвета 优先取专用键，避免被「Цвет」基础色抢先
    if _is_color_name_attr(attr_name):
        for key in ("Название цвета", "название цвета", "颜色", "区分项", "规格"):
            if key in overrides and overrides[key]:
                return overrides[key]
        for key, value in overrides.items():
            if "названиецвета" in _norm(key).replace(" ", "") and value:
                return value

    source = _find_source_value(attr_name, mapped)
    if source:
        return source
    name_norm = _norm(attr_name)
    preferred_keys: tuple[str, ...]
    if any(token in name_norm for token in ("рукав", "sleeve", "袖")):
        preferred_keys = ("袖长", "рукав", "sleeve", "размер", "size", "尺码")
    elif _is_size_aspect_name(attr_name):
        preferred_keys = (
            "размер",
            "size",
            "尺码",
            "规格",
            "ступен",
            "袖长",
            "рукав",
            "sleeve",
        )
    elif _is_color_name_attr(attr_name):
        preferred_keys = ("названиецвета", "颜色", "区分项")
    elif _is_color_aspect_name(attr_name):
        preferred_keys = ("цветтовара", "цвет", "color", "颜色")
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
    variant_aspect: color | size | both（双区分项同时写颜色+尺码）。
    """
    aspect_mode = normalize_variant_aspect(variant_aspect)
    overrides = enrich_variant_aspect_fields(variant_attributes)

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
    has_size_override = bool(
        overrides.get("尺码")
        or overrides.get("Размер")
        or listing_size_label(
            overrides.get("规格"),
            overrides.get("区分项"),
            overrides.get("尺码"),
            overrides.get("Размер"),
        )
    )

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
        is_size = _is_size_aspect_name(name)
        # 仅「纯尺码轴」去掉颜色；both/color 保留颜色
        if aspect_mode == "size" and is_color:
            drop_ids.add(attr_id)
            continue
        # 纯颜色轴且无尺码数据时跳过尺码属性；有尺码则双写（防双轴塌缩）
        if aspect_mode == "color" and is_size and not has_size_override:
            continue

        if not overrides:
            continue
        source_value = _aspect_source_from_overrides(name, overrides)
        if not source_value:
            continue
        name_norm = _norm(name)
        is_size_mm = is_size and ("мм" in name_norm or "mm" in name_norm)
        is_color_name = _is_color_name_attr(name)
        if contains_cjk(source_value) or is_size_mm:
            if is_color and not is_color_name:
                # 颜色字典只接受纯色名，绝不夹带尺码
                source_value = listing_color_label(source_value, edit_title)
            elif is_color_name:
                phrase = _pattern_color_phrase_from_cjk(source_value)
                base = listing_color_label(source_value, edit_title) or ""
                source_value = _clean_color_display_name(
                    f"{base} {phrase}".strip() if phrase else source_value
                )
            elif is_size_mm:
                packed_color, packed_size = parse_packed_color_size(source_value)
                source_value = (
                    size_label_to_mm(packed_size)
                    or size_label_to_mm(listing_size_label(source_value))
                    or size_label_to_mm(strip_cjk(source_value))
                    or ""
                )
            elif is_size:
                source_value = listing_size_label(source_value) or strip_cjk(source_value)
            else:
                source_value = strip_cjk(source_value)
        elif is_size and not is_size_mm:
            source_value = listing_size_label(source_value) or source_value
        if is_color:
            if is_color_name:
                # 保留「синий с китом」等区分短语，禁止压回纯色
                source_value = _clean_color_display_name(source_value) or str(source_value or "").strip()
            else:
                source_value = listing_color_label(source_value, edit_title) or str(source_value or "").strip()
                # 去掉误拼进去的尺码，只留颜色词
                if source_value and _color_has_size_noise(source_value):
                    source_value = infer_color_label(source_value, edit_title) or source_value.split()[0]
        if not source_value or contains_cjk(source_value):
            continue

        dictionary_id = attr.get("dictionary_id")
        has_dictionary = bool(_as_int(dictionary_id))
        payload_value: dict[str, Any]
        if has_dictionary:
            # 字典属性必须用 dictionary_value_id；未命中则跳过，禁止自由文本
            aspect_queries = [source_value, edit_title]
            if _is_animal_size_attr(name):
                aspect_queries = _pet_size_search_queries(source_value, edit_title) + aspect_queries
            picked = pick_dictionary_value(
                client=client,
                attribute_id=attr_id,
                description_category_id=description_category_id,
                type_id=type_id,
                queries=aspect_queries,
                attribute_name=name,
            )
            if not picked:
                continue
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
