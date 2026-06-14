from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from bs4 import Tag

ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")


@dataclass
class VariantOption:
    asin: str
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def size(self) -> str | None:
        return self._find_attribute("size")

    @property
    def color(self) -> str | None:
        return self._find_attribute("color")

    def _find_attribute(self, keyword: str) -> str | None:
        for key, value in self.attributes.items():
            normalized = key.lower().replace("_name", "")
            if normalized == keyword or keyword in normalized:
                return value
        return None


def parse_variants(html: str, doc: BeautifulSoup, fallback_asin: str) -> list[VariantOption]:
    json_variants = _parse_variants_from_json(html)
    if json_variants:
        return json_variants

    dom_variants = _parse_variants_from_dom(doc)
    if dom_variants:
        return dom_variants

    return [VariantOption(asin=fallback_asin.upper())]


def _parse_variants_from_json(html: str) -> list[VariantOption]:
    display_data = _extract_js_json_object(html, "dimensionValuesDisplayData")
    if not display_data:
        return []

    variation_values = _extract_js_json_object(html, "variationValues") or {}
    display_labels = _extract_js_json_object(html, "variationDisplayLabels") or {}
    dimension_keys = list(variation_values.keys())

    variants: list[VariantOption] = []
    for asin, values in display_data.items():
        normalized_asin = str(asin).strip().upper()
        if not ASIN_PATTERN.match(normalized_asin):
            continue

        attributes: dict[str, str] = {}
        if isinstance(values, list):
            for index, value in enumerate(values):
                if value in (None, "", "Please Select"):
                    continue
                dimension_key = dimension_keys[index] if index < len(dimension_keys) else f"dimension_{index}"
                label = str(display_labels.get(dimension_key, dimension_key))
                attributes[label] = str(value)
        elif isinstance(values, dict):
            for dimension_key, value in values.items():
                if value in (None, "", "Please Select"):
                    continue
                label = str(display_labels.get(dimension_key, dimension_key))
                attributes[label] = str(value)

        variants.append(VariantOption(asin=normalized_asin, attributes=attributes))

    return variants


def _parse_variants_from_dom(doc: BeautifulSoup) -> list[VariantOption]:
    variants_by_asin: dict[str, VariantOption] = {}

    for row in doc.select('[id^="inline-twister-row-"], [id^="variation_"]'):
        dimension_key = _extract_dimension_key(row.get("id", ""))
        label = _extract_dimension_label(row, dimension_key)

        for element in row.select("li[data-asin]"):
            asin = element.get("data-asin", "").strip().upper()
            if not ASIN_PATTERN.match(asin):
                continue

            value = _extract_twister_label(element)
            if not value:
                continue

            if asin not in variants_by_asin:
                variants_by_asin[asin] = VariantOption(asin=asin)
            variants_by_asin[asin].attributes[label] = value

    return list(variants_by_asin.values())


def _extract_dimension_key(element_id: str) -> str:
    if element_id.startswith("inline-twister-row-"):
        return element_id.replace("inline-twister-row-", "")
    if element_id.startswith("variation_"):
        return element_id.replace("variation_", "")
    return element_id


def _extract_dimension_label(row: Tag, dimension_key: str) -> str:
    label_element = row.select_one(
        ".a-form-label, .inline-twister-dim-title-value, .dimension-label, label"
    )
    if label_element:
        text = label_element.get_text(strip=True)
        if text:
            return text.rstrip(":").strip()

    return dimension_key.replace("_name", "").replace("_", " ").title()


def _extract_twister_label(element: Tag) -> str | None:
    for selector in (
        ".swatch-title-text-display",
        ".a-size-base.a-color-base",
        ".twisterTextDiv",
    ):
        label_element = element.select_one(selector)
        if label_element:
            text = label_element.get_text(strip=True)
            if text:
                return _clean_twister_label(text)

    return _clean_twister_label(element.get_text(" ", strip=True))


def _clean_twister_label(text: str) -> str | None:
    cleaned = re.sub(r"[\$€£¥][\d,.]+", "", text)
    cleaned = re.sub(r"CNY\s*[\d,.]+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _extract_js_json_object(html: str, key: str) -> dict | list | None:
    marker = f'"{key}"'
    start_index = html.find(marker)
    if start_index < 0:
        return None

    colon_index = html.find(":", start_index)
    if colon_index < 0:
        return None

    cursor = colon_index + 1
    while cursor < len(html) and html[cursor].isspace():
        cursor += 1

    if cursor >= len(html) or html[cursor] not in "{[":
        return None

    opening = html[cursor]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for index in range(cursor, len(html)):
        char = html[index]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[cursor : index + 1])
                except json.JSONDecodeError:
                    return None

    return None
