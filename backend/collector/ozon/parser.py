from __future__ import annotations

import json
import re
from typing import Any


def widget_name(key: str) -> str:
    return str(key).split("-")[0]


def extract_composer_from_html(html: str) -> dict[str, Any] | None:
    if not html:
        return None

    # Ozon sometimes embeds widgetStates in inline scripts on the HTML page.
    marker = '"widgetStates"'
    start = html.find(marker)
    if start < 0:
        return None

    brace_start = html.find("{", start)
    if brace_start < 0:
        return None

    depth = 0
    for index in range(brace_start, len(html)):
        char = html[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                snippet = html[brace_start:index + 1]
                try:
                    widget_states = json.loads(snippet)
                except json.JSONDecodeError:
                    return None
                if isinstance(widget_states, dict) and widget_states:
                    return {"widgetStates": widget_states}
                return None
    return None


def widget(page: dict[str, Any], name: str) -> dict[str, Any] | None:
    widget_states = page.get("widgetStates") or {}
    key = next((k for k in widget_states if widget_name(k) == name), None)
    if not key:
        return None
    try:
        return json.loads(widget_states[key])
    except (json.JSONDecodeError, TypeError):
        return None


def widgets(page: dict[str, Any], name: str) -> list[dict[str, Any]]:
    widget_states = page.get("widgetStates") or {}
    parsed: list[dict[str, Any]] = []
    for key in widget_states:
        if widget_name(key) != name:
            continue
        try:
            value = json.loads(widget_states[key])
            if isinstance(value, dict):
                parsed.append(value)
        except (json.JSONDecodeError, TypeError):
            continue
    return parsed


def parse_rating(text: Any) -> float | None:
    """Ozon 评分是 0–5。中文页面上的「16 和 1 P」这类文案不能拿去 float()。"""
    raw = str(text or "").replace("\u00a0", "").replace("\u2009", "").replace(" ", "")
    raw = raw.replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if value < 0 or value > 5:
        return None
    return value


def price_to_number(text: Any) -> int | None:
    if isinstance(text, bool) or text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text) if text > 0 else None
    if isinstance(text, dict):
        for key in ("price", "text", "cardPrice", "value"):
            if key in text:
                parsed = price_to_number(text.get(key))
                if parsed is not None:
                    return parsed
        return None
    if not isinstance(text, str):
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def clean_url(link: Any) -> str | None:
    if not link:
        return None
    path = str(link).split("?")[0]
    return path if path.startswith("http") else f"https://www.ozon.ru{path}"


def sku_from_url(url: Any) -> str | None:
    text = str(url or "")
    match = re.search(r"-(\d+)/?(?:\?|$)", text) or re.search(r"(\d{6,})", text)
    return match.group(1) if match else None


def parse_search_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not item:
        return None

    main_state = item.get("mainState") if isinstance(item.get("mainState"), list) else []

    price_block = next((s.get("priceV2") for s in main_state if s.get("type") == "priceV2"), None)
    prices = (price_block or {}).get("price") or []
    price = price_to_number(next((p.get("text") for p in prices if p.get("textStyle") == "PRICE"), None))
    old_price = price_to_number(
        next((p.get("text") for p in prices if p.get("textStyle") == "ORIGINAL_PRICE"), None)
    )

    name = next((s.get("textDS", {}).get("text") for s in main_state if s.get("id") == "name"), None)

    rating: float | None = None
    reviews: int | None = None
    rating_list = next(
        (
            s.get("labelListV2", {}).get("items")
            for s in main_state
            if s.get("labelListV2") and "ic_s_star" in json.dumps(s.get("labelListV2"), ensure_ascii=False)
        ),
        None,
    )
    if not isinstance(rating_list, list):
        rating_list = next(
            (
                s.get("labelListV2", {}).get("items")
                for s in main_state
                if s.get("labelListV2") and len(s.get("labelListV2", {}).get("items") or []) >= 2
            ),
            None,
        )
    if isinstance(rating_list, list):
        texts = [x.get("text", {}).get("text") for x in rating_list if x.get("type") == "text"]
        if texts and texts[0]:
            rating = parse_rating(texts[0])
        if len(texts) > 1 and texts[1]:
            reviews = price_to_number(texts[1])

    badge_pattern = re.compile(
        r"^(стало дешевле|оригинал|хит|новинка|акция|распродажа|выбор|бестселлер|ozon|premium|самовывоз|скидка)",
        re.IGNORECASE,
    )
    brand: str | None = None
    label_lists = [
        s.get("labelListV2")
        for s in main_state
        if s.get("labelListV2") and "ic_s_star" not in json.dumps(s.get("labelListV2"), ensure_ascii=False)
    ]
    for label_list in label_lists:
        for entry in (label_list or {}).get("items") or []:
            candidate = (entry.get("text") or {}).get("text")
            if candidate and not badge_pattern.match(candidate.strip()):
                brand = candidate.strip()
                break
        if brand:
            break

    url = clean_url((item.get("action") or {}).get("link"))
    sku = str(item.get("sku") or item.get("id") or sku_from_url(url) or "") or None

    image = None
    tile_image = item.get("tileImage") or {}
    for tile_item in tile_image.get("items") or []:
        link = (tile_item.get("image") or {}).get("link")
        if link:
            image = link
            break
    if not image:
        image = tile_image.get("coverImage")

    if not sku or not price:
        return None

    return {
        "sku": sku,
        "name": name,
        "price": price,
        "old_price": old_price if old_price and old_price > price else None,
        "discount": (price_block or {}).get("discount"),
        "rating": rating,
        "reviews": reviews,
        "brand": brand,
        "url": url,
        "image": image,
    }


_RECOMMENDATION_TITLE_MARKERS = (
    "вам понравится",
    "подобрали для вас",
    "рекоменд",
    "похож",
    "you may also like",
    "您可能喜欢",
    "猜你喜欢",
    "为你推荐",
    "相似",
    "类似",
)


def _grid_header_text(grid: dict[str, Any]) -> str:
    header = grid.get("header")
    if not isinstance(header, dict):
        return ""
    title = header.get("title")
    if isinstance(title, dict):
        return str(title.get("text") or "").strip()
    if isinstance(title, str):
        return title.strip()
    return ""


def is_recommendation_grid(grid: dict[str, Any]) -> bool:
    """店铺页底部「您可能喜欢」等推荐架，商品不属于当前店铺。"""
    text = _grid_header_text(grid).lower()
    if not text:
        return False
    return any(marker in text for marker in _RECOMMENDATION_TITLE_MARKERS)


def catalog_listing_grids(page: dict[str, Any]) -> list[dict[str, Any]]:
    grids = widgets(page, "tileGridDesktop")
    if not grids:
        for legacy_name in ("searchResultsV2", "tileGrid"):
            grids = widgets(page, legacy_name)
            if grids:
                break
    return [grid for grid in grids if grid.get("items") and not is_recommendation_grid(grid)]


def parse_listing_page(page: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    raw_items: list[Any] = []
    for grid in catalog_listing_grids(page):
        raw_items.extend(grid.get("items") or [])
    items = [parsed for parsed in (parse_search_item(item) for item in raw_items) if parsed]
    return items[:limit]


def _next_page_from_paginator(paginator: Any) -> str | None:
    if not isinstance(paginator, dict):
        return None
    next_page = paginator.get("nextPage")
    if not isinstance(next_page, str) or not next_page.strip():
        return None
    path = next_page.strip()
    return path if path.startswith("/") else f"/{path.lstrip('/')}"


def extract_next_page_path(page: dict[str, Any]) -> str | None:
    """下一页可能在商品网格里，也可能在单独的 infiniteVirtualPaginator 组件上。"""
    found: list[str] = []
    for grid in catalog_listing_grids(page):
        path = _next_page_from_paginator(grid.get("infiniteVirtualPaginator") or grid.get("paginator"))
        if path:
            found.append(path)
    for paginator in widgets(page, "infiniteVirtualPaginator"):
        path = _next_page_from_paginator(paginator)
        if path and path not in found:
            found.append(path)
    if not found:
        return None
    for path in found:
        if "/seller/" in path:
            return path
    return found[0]


def rs_text(nodes: Any) -> str:
    if nodes is None:
        return ""
    if isinstance(nodes, str):
        return nodes.strip()
    if isinstance(nodes, dict):
        return str(nodes.get("text") or nodes.get("content") or "").strip()
    if not isinstance(nodes, list):
        return str(nodes).strip()
    parts = [str(node.get("text") or node.get("content") or "") for node in nodes if isinstance(node, dict)]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _characteristic_pair(entry: dict[str, Any]) -> tuple[str, str] | None:
    title_block = entry.get("title")
    title = rs_text((title_block or {}).get("textRs")) if isinstance(title_block, dict) else ""
    if not title and isinstance(title_block, str):
        title = title_block.strip()
    value = rs_text(entry.get("values") or entry.get("contentRS") or entry.get("valueRs"))
    if not value and entry.get("short"):
        value = rs_text(entry.get("short"))
    if not value and entry.get("content") is not None and not isinstance(entry.get("content"), list):
        value = str(entry.get("content")).strip()
    if title and value:
        return title, value
    return None


def parse_characteristics(page: dict[str, Any], widget_name: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for widget_data in widgets(page, widget_name):
        for entry in widget_data.get("characteristics") or []:
            if not isinstance(entry, dict):
                continue
            nested = entry.get("content")
            if isinstance(nested, list):
                for inner in nested:
                    if isinstance(inner, dict):
                        pair = _characteristic_pair(inner)
                        if pair:
                            attributes[pair[0]] = pair[1]
                continue
            pair = _characteristic_pair(entry)
            if pair:
                attributes[pair[0]] = pair[1]
    return attributes


def parse_category_name(page: dict[str, Any]) -> str | None:
    crumbs = widget(page, "breadCrumbs")
    items = (crumbs or {}).get("breadcrumbs") or (crumbs or {}).get("items") or []
    labels: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = rs_text(item.get("textRs")) or str(item.get("text") or item.get("title") or "").strip()
        if text:
            labels.append(text)
    if len(labels) >= 2:
        return " / ".join(labels[:-1])
    if labels:
        return labels[0]
    return None


def _as_positive_int_id(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, float) and value.is_integer() and value > 0:
        return str(int(value))
    text = str(value).strip()
    if text.isdigit() and int(text) > 0:
        return text
    return None


def _pick_id(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        found = _as_positive_int_id(payload.get(key))
        if found:
            return found
    return None


def _iter_tracking_dicts(page: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    tracking = page.get("layoutTrackingInfo")
    if isinstance(tracking, str):
        try:
            tracking = json.loads(tracking)
        except json.JSONDecodeError:
            tracking = None
    if isinstance(tracking, dict):
        found.append(tracking)

    for widget_data in _iter_widget_json(page):
        cell = widget_data.get("cellTrackingInfo")
        if isinstance(cell, dict):
            found.append(cell)
            product = cell.get("product")
            if isinstance(product, dict):
                found.append(product)
        product = widget_data.get("product")
        if isinstance(product, dict):
            found.append(product)
        for key in ("trackingInfo", "params"):
            block = widget_data.get(key)
            if isinstance(block, dict):
                found.append(block)
    return found


def parse_description_category_and_type(
    page: dict[str, Any],
    page2: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """从 PDP 追踪信息中提取 Seller API 所需的 description_category_id / type_id。"""
    description_category_id: str | None = None
    type_id: str | None = None

    category_keys = (
        "description_category_id",
        "descriptionCategoryId",
        "descriptionCategoryID",
        "categoryId",
        "category_id",
    )
    type_keys = ("type_id", "typeId", "typeID", "descriptionTypeId", "description_type_id")

    for source_page in (page, page2):
        if not source_page:
            continue
        for payload in _iter_tracking_dicts(source_page):
            if description_category_id is None:
                description_category_id = _pick_id(payload, category_keys)
            if type_id is None:
                type_id = _pick_id(payload, type_keys)
            if description_category_id and type_id:
                return description_category_id, type_id

    # 面包屑链接里的数字可作为兜底类目 ID（不一定等于 description_category_id）
    if description_category_id is None:
        crumbs = widget(page, "breadCrumbs") or {}
        for item in crumbs.get("breadcrumbs") or crumbs.get("items") or []:
            if not isinstance(item, dict):
                continue
            link = (
                item.get("link")
                or item.get("url")
                or ((item.get("action") or {}).get("link") if isinstance(item.get("action"), dict) else None)
            )
            if not link:
                continue
            match = re.search(r"/category/[^/]*?(\d{3,})/?", str(link))
            if match:
                description_category_id = match.group(1)
                break

    return description_category_id, type_id


def _extract_rich_annotation_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return ""
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        raw = parsed

    texts: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "text" and isinstance(node.get("content"), str):
            texts.append(node["content"])
        if isinstance(node.get("text"), str) and node.get("type") in {None, "text"}:
            texts.append(node["text"])
        if isinstance(node.get("items"), list):
            for item in node["items"]:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("content"), str):
                    texts.append(item["content"])
                else:
                    walk(item)
        for key, child in node.items():
            if key in {"items", "img"}:
                continue
            if isinstance(child, (list, dict)):
                walk(child)

    if isinstance(raw, dict):
        walk(raw.get("content") or raw)
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def parse_description(page: dict[str, Any] | None) -> str:
    if not page:
        return ""
    for desc_widget in widgets(page, "webDescription"):
        for key in ("richAnnotationJson", "richAnnotation", "textRs", "text"):
            raw = desc_widget.get(key)
            if key in {"textRs", "text"}:
                text = rs_text(raw) if key == "textRs" else str(raw or "").strip()
                if text:
                    return text
                continue
            text = _extract_rich_annotation_text(raw)
            if text:
                return text
    return ""


def _find_attribute(attributes: dict[str, str], aliases: tuple[str, ...]) -> str | None:
    for key, value in attributes.items():
        lower = key.lower()
        if any(alias in lower for alias in aliases):
            text = str(value).strip()
            if text:
                return text
    return None


def derive_size_and_weight(attributes: dict[str, str]) -> tuple[str | None, str | None]:
    length = _find_attribute(attributes, ("длина", "length", "长度"))
    width = _find_attribute(attributes, ("ширина", "width", "宽度"))
    height = _find_attribute(attributes, ("высота", "height", "高度"))
    dims = [value for value in (length, width, height) if value]
    size = f"{'×'.join(dims)} mm" if dims else None
    weight = _find_attribute(attributes, ("вес", "weight", "重量", "масса"))
    return size, weight


def parse_product_score(page: dict[str, Any]) -> tuple[float | None, int | None]:
    score_widget = widget(page, "webSingleProductScore") or widget(page, "webReviewProductScore")
    text = (score_widget or {}).get("text") or json.dumps(score_widget or {}, ensure_ascii=False)
    rating_match = re.search(r"(\d[.,]\d)", text)
    reviews_match = re.search(r"(\d[\d\s]*)\s*отзыв", text, re.IGNORECASE)
    rating = float(rating_match.group(1).replace(",", ".")) if rating_match else None
    reviews = price_to_number(reviews_match.group(1)) if reviews_match else None
    return rating, reviews


def parse_product_details(base_page: dict[str, Any], page2: dict[str, Any] | None = None) -> dict[str, Any]:
    heading = widget(base_page, "webProductHeading")
    price_widget = widget(base_page, "webPrice")
    gallery = widget(base_page, "webGallery")

    sku = str((gallery or {}).get("sku") or "")
    if not sku and base_page.get("layoutTrackingInfo"):
        try:
            sku = str(json.loads(base_page["layoutTrackingInfo"]).get("sku") or "")
        except (json.JSONDecodeError, TypeError):
            sku = ""
    if not sku:
        sku = _extract_sku_from_widgets(base_page) or ""
    if not sku:
        seo_links = (base_page.get("seo") or {}).get("link") or []
        if seo_links:
            sku = sku_from_url((seo_links[0] or {}).get("href")) or ""

    url = None
    seo_links = (base_page.get("seo") or {}).get("link") or []
    if seo_links:
        url = clean_url((seo_links[0] or {}).get("href"))
    if not url and sku:
        url = f"https://www.ozon.ru/product/{sku}/"

    rating, reviews = parse_product_score(base_page)
    images: list[str] = []
    if gallery and gallery.get("coverImage"):
        images.append(gallery["coverImage"])
    for image in (gallery or {}).get("images") or []:
        src = image.get("src") or image.get("image") if isinstance(image, dict) else image
        if isinstance(src, str):
            images.append(src)

    attributes: dict[str, str] = {}
    attributes.update(parse_characteristics(base_page, "webShortCharacteristics"))
    if page2:
        attributes.update(parse_characteristics(page2, "webCharacteristics"))
        attributes.update(parse_characteristics(page2, "webShortCharacteristics"))

    description = parse_description(page2) or parse_description(base_page)
    category_name = parse_category_name(base_page)
    description_category_id, type_id = parse_description_category_and_type(base_page, page2)
    size, weight = derive_size_and_weight(attributes)

    # 普通售价优先（页面灰字），Ozon 卡价单独保存，避免把绿框卡价当成售价
    card_price = price_to_number((price_widget or {}).get("cardPrice"))
    price = price_to_number((price_widget or {}).get("price")) if price_widget else None
    if price is None:
        price = card_price
    if price is None:
        price = _extract_price_from_widgets(base_page)

    name = (heading or {}).get("title") or (base_page.get("seo") or {}).get("title")
    if not name:
        name = _extract_title_from_widgets(base_page)

    aspect_variants = parse_product_aspects(base_page)
    if page2:
        aspect_variants = merge_aspect_variants(aspect_variants, parse_product_aspects(page2))

    # 当前选中规格写回 attributes，便于单变体场景
    for item in aspect_variants:
        if item.get("active") and isinstance(item.get("attributes"), dict):
            for key, value in item["attributes"].items():
                if value and key not in attributes:
                    attributes[str(key)] = str(value)

    return {
        "sku": sku or None,
        "name": name,
        "url": url,
        "price": price,
        "card_price": card_price,
        "old_price": price_to_number((price_widget or {}).get("originalPrice")),
        "rating": rating,
        "reviews": reviews,
        "brand": (heading or {}).get("brand") or None,
        "image": images[0] if images else _extract_image_from_widgets(base_page),
        "images": list(dict.fromkeys(images))[:10],
        "description": description,
        "attributes": attributes,
        "category_name": category_name,
        "description_category_id": description_category_id,
        "type_id": type_id,
        "size": size,
        "weight": weight,
        "aspect_variants": aspect_variants,
    }


def parse_product_aspects(page: dict[str, Any]) -> list[dict[str, Any]]:
    """
    解析 PDP 规格选择器（颜色/尺码等），得到兄弟 SKU 列表。
    每项: sku / url / label / attributes / image / price / active
    多区分项时，同一 SKU 会合并多个 aspect 的属性。
    """
    by_sku: dict[str, dict[str, Any]] = {}

    def upsert(
        *,
        sku: str,
        aspect_name: str,
        value: str,
        url: str | None = None,
        image: str | None = None,
        price: int | None = None,
        active: bool = False,
    ) -> None:
        sku = str(sku).strip()
        if not sku.isdigit():
            return
        entry = by_sku.get(sku)
        if entry is None:
            entry = {
                "sku": sku,
                "url": url,
                "attributes": {},
                "image": image,
                "price": price,
                "active": active,
                "label": "",
            }
            by_sku[sku] = entry
        if aspect_name and value:
            entry["attributes"][str(aspect_name)] = str(value)
        if url and not entry.get("url"):
            entry["url"] = url
        if image and not entry.get("image"):
            entry["image"] = image
        if price is not None and entry.get("price") is None:
            entry["price"] = price
        if active:
            entry["active"] = True

    # 1) 常见 widget：webAspects / webAspectsV2 / aspects*
    for name in ("webAspects", "webAspectsV2", "webAspectsShelf", "aspects"):
        for block in widgets(page, name):
            _ingest_aspects_block(block, upsert)

    # 2) 兜底：扫描所有 widget 里的 aspects 数组
    for widget_data in _iter_widget_json(page):
        if isinstance(widget_data.get("aspects"), list):
            _ingest_aspects_block(widget_data, upsert)
        for nest_key in ("data", "state", "payload"):
            nested = widget_data.get(nest_key)
            if isinstance(nested, dict) and isinstance(nested.get("aspects"), list):
                _ingest_aspects_block(nested, upsert)

    return finalize_aspect_variants(list(by_sku.values()))


def finalize_aspect_variants(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """补全 label / url，并把当前选中的 SKU 排到前面。"""
    results: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sku = str(entry.get("sku") or "").strip()
        if not sku.isdigit():
            continue
        attrs = {
            str(key): str(value)
            for key, value in (entry.get("attributes") or {}).items()
            if str(key).strip() and str(value).strip()
        }
        label = " / ".join(str(value) for value in attrs.values() if value)
        url = entry.get("url")
        if not url:
            url = f"https://www.ozon.ru/product/{sku}/"
        image = entry.get("image")
        if isinstance(image, str) and "/wc140/" in image:
            image = image.replace("/wc140/", "/wc1200/")
        results.append(
            {
                "sku": sku,
                "url": clean_url(url) or f"https://www.ozon.ru/product/{sku}/",
                "attributes": attrs,
                "image": image,
                "price": entry.get("price"),
                "active": bool(entry.get("active")),
                "label": label,
            }
        )
    results.sort(key=lambda item: (0 if item.get("active") else 1, item.get("sku") or ""))
    return results


def merge_aspect_variants(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    合并多页 aspects。多区分项商品首屏往往只带「当前颜色的尺码 + 当前尺码的颜色」，
    需要把兄弟 SKU 页的 aspects 合并，才能得到每个 SKU 的完整属性。
    """
    by_sku: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "").strip()
            if not sku.isdigit():
                continue
            entry = by_sku.get(sku)
            if entry is None:
                entry = {
                    "sku": sku,
                    "url": item.get("url"),
                    "attributes": {},
                    "image": item.get("image"),
                    "price": item.get("price"),
                    "active": bool(item.get("active")),
                    "label": "",
                }
                by_sku[sku] = entry
            attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
            for key, value in attrs.items():
                text_key = str(key).strip()
                text_value = str(value).strip()
                if text_key and text_value:
                    entry["attributes"][text_key] = text_value
            if item.get("url") and not entry.get("url"):
                entry["url"] = item.get("url")
            if item.get("image") and not entry.get("image"):
                entry["image"] = item.get("image")
            if item.get("price") is not None and entry.get("price") is None:
                entry["price"] = item.get("price")
            if item.get("active"):
                entry["active"] = True
    return finalize_aspect_variants(list(by_sku.values()))


def aspect_variant_skus(aspect_variants: list[dict[str, Any]]) -> list[str]:
    skus: list[str] = []
    seen: set[str] = set()
    for item in aspect_variants or []:
        sku = str((item or {}).get("sku") or "").strip()
        if not sku.isdigit() or sku in seen:
            continue
        seen.add(sku)
        skus.append(sku)
    return skus


def _ingest_aspects_block(block: dict[str, Any], upsert: Any) -> None:
    aspects = block.get("aspects")
    if not isinstance(aspects, list):
        return
    for aspect in aspects:
        if not isinstance(aspect, dict):
            continue
        aspect_name = str(
            aspect.get("name")
            or aspect.get("aspectName")
            or aspect.get("aspectKey")
            or aspect.get("key")
            or aspect.get("title")
            or "Вариант"
        ).strip() or "Вариант"
        variants = aspect.get("variants") or aspect.get("items") or aspect.get("values") or []
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            sku = str(
                variant.get("sku")
                or variant.get("id")
                or variant.get("productId")
                or sku_from_url(variant.get("link") or variant.get("url") or "")
                or ""
            )
            value = _aspect_variant_label(variant)
            link = variant.get("link") or variant.get("url") or variant.get("deeplink")
            data = variant.get("data") if isinstance(variant.get("data"), dict) else {}
            image = (
                variant.get("coverImage")
                or variant.get("coverImageUrl")
                or variant.get("image")
                or data.get("coverImage")
                or data.get("picture")
                or data.get("image")
            )
            if isinstance(image, dict):
                image = image.get("src") or image.get("link") or image.get("url")
            if isinstance(image, str) and "/wc140/" in image:
                image = image.replace("/wc140/", "/wc1200/")
            price: int | None = None
            raw_price = variant.get("price")
            if raw_price is None:
                raw_price = variant.get("cardPrice")
            if isinstance(raw_price, (int, float)) and not isinstance(raw_price, bool):
                price = int(raw_price) if raw_price > 0 else None
            else:
                price = price_to_number(raw_price)
            if price is None and data.get("price") is not None:
                price = price_to_number(data.get("price"))
            if price is None and variant.get("finalPrice") is not None:
                try:
                    price = int(float(variant.get("finalPrice")))
                except (TypeError, ValueError):
                    price = None
            active = bool(
                variant.get("active")
                or variant.get("selected")
                or variant.get("isSelected")
                or variant.get("isActive")
            )
            upsert(
                sku=sku,
                aspect_name=aspect_name,
                value=value,
                url=clean_url(link),
                image=str(image) if image else None,
                price=price,
                active=active,
            )


def _aspect_variant_label(variant: dict[str, Any]) -> str:
    data = variant.get("data")
    if isinstance(data, dict):
        # 新版 webAspects：真实规格在 searchableText / textRs，title 往往是商品名
        searchable = data.get("searchableText")
        if searchable:
            return str(searchable).strip()
        text_rs = data.get("textRs")
        if isinstance(text_rs, list):
            parts: list[str] = []
            for item in text_rs:
                if isinstance(item, dict) and item.get("content"):
                    parts.append(str(item["content"]).strip())
                elif isinstance(item, str) and item.strip():
                    parts.append(item.strip())
            if parts:
                return " ".join(parts)
        for key in ("text", "name", "label", "value"):
            if data.get(key):
                return str(data[key]).strip()
    for key in ("text", "name", "label", "value", "content"):
        if variant.get(key):
            return str(variant[key]).strip()
    return str(variant.get("sku") or "").strip()


def _extract_sku_from_widgets(page: dict[str, Any]) -> str | None:
    for widget_data in _iter_widget_json(page):
        product = (widget_data.get("cellTrackingInfo") or {}).get("product") or {}
        sku = product.get("id") or product.get("sku")
        if sku:
            return str(sku)
        if widget_data.get("sku"):
            return str(widget_data["sku"])
    return None


def _extract_price_from_widgets(page: dict[str, Any]) -> int | None:
    for widget_data in _iter_widget_json(page):
        for key in ("price", "cardPrice", "finalPrice"):
            if key not in widget_data:
                continue
            parsed = price_to_number(widget_data.get(key))
            if parsed is not None:
                return parsed
    return None


def _extract_title_from_widgets(page: dict[str, Any]) -> str | None:
    for widget_data in _iter_widget_json(page):
        product = (widget_data.get("cellTrackingInfo") or {}).get("product") or {}
        if product.get("title"):
            return str(product["title"])
        if widget_data.get("title"):
            return str(widget_data["title"])
    return None


def _extract_image_from_widgets(page: dict[str, Any]) -> str | None:
    for widget_data in _iter_widget_json(page):
        if widget_data.get("coverImage"):
            return str(widget_data["coverImage"])
        product = (widget_data.get("cellTrackingInfo") or {}).get("product") or {}
        if product.get("coverImage"):
            return str(product["coverImage"])
    return None


def _iter_widget_json(page: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for raw in (page.get("widgetStates") or {}).values():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                results.append(parsed)
        except (json.JSONDecodeError, TypeError):
            continue
    return results
