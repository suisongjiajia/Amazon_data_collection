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


def price_to_number(text: Any) -> int | None:
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
            rating = float(str(texts[0]).replace(",", "."))
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


def parse_listing_page(page: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
    grid = widget(page, "tileGridDesktop")
    if not grid:
        # Legacy widget name still seen on some pages.
        for legacy_name in ("searchResultsV2", "tileGrid"):
            legacy = widget(page, legacy_name)
            if legacy and legacy.get("items"):
                grid = legacy
                break

    raw_items = (grid or {}).get("items") or []
    items = [parsed for parsed in (parse_search_item(item) for item in raw_items) if parsed]
    return items[:limit]


def extract_next_page_path(page: dict[str, Any]) -> str | None:
    grid = widget(page, "tileGridDesktop")
    if not grid:
        return None
    paginator = grid.get("infiniteVirtualPaginator") or grid.get("paginator") or {}
    next_page = paginator.get("nextPage")
    if isinstance(next_page, str) and next_page.strip():
        return next_page if next_page.startswith("/") else f"/{next_page.lstrip('/')}"
    return None


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

    price = price_to_number((price_widget or {}).get("cardPrice"))
    if price is None and price_widget:
        price = price_to_number(price_widget.get("price"))
    if price is None:
        price = _extract_price_from_widgets(base_page)

    name = (heading or {}).get("title") or (base_page.get("seo") or {}).get("title")
    if not name:
        name = _extract_title_from_widgets(base_page)

    aspect_variants = parse_product_aspects(base_page)
    if page2:
        # page2 偶尔也会带 aspects；合并去重
        merged = {item["sku"]: item for item in aspect_variants}
        for item in parse_product_aspects(page2):
            existing = merged.get(item["sku"])
            if existing is None:
                merged[item["sku"]] = item
            else:
                attrs = dict(existing.get("attributes") or {})
                attrs.update(item.get("attributes") or {})
                existing["attributes"] = attrs
                if not existing.get("image") and item.get("image"):
                    existing["image"] = item["image"]
                if existing.get("price") is None and item.get("price") is not None:
                    existing["price"] = item["price"]
        aspect_variants = list(merged.values())

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
        # 某些结构把 aspects 放在 data / state 下
        for nest_key in ("data", "state", "payload"):
            nested = widget_data.get(nest_key)
            if isinstance(nested, dict) and isinstance(nested.get("aspects"), list):
                _ingest_aspects_block(nested, upsert)

    results: list[dict[str, Any]] = []
    for entry in by_sku.values():
        attrs = entry.get("attributes") or {}
        label = " / ".join(str(v) for v in attrs.values() if v)
        entry["label"] = label
        if not entry.get("url"):
            entry["url"] = f"https://www.ozon.ru/product/{entry['sku']}/"
        results.append(entry)
    # 当前选中的排前面
    results.sort(key=lambda item: (0 if item.get("active") else 1, item.get("sku") or ""))
    return results


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
            raw_price = variant.get("price")
            if raw_price is None:
                raw_price = variant.get("cardPrice")
            if isinstance(raw_price, (int, float)):
                price = int(raw_price)
            else:
                price = price_to_number(str(raw_price or ""))
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
        if widget_data.get("cardPrice"):
            return price_to_number(widget_data.get("cardPrice"))
        if widget_data.get("price"):
            return price_to_number(widget_data.get("price"))
        if widget_data.get("finalPrice"):
            return price_to_number(str(widget_data.get("finalPrice")))
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
