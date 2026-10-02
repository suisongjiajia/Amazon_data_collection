"""Fix edit 73 stair variants: distinct colors + step sizes for Ozon merge card."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import get_connection  # noqa: E402
from db.ozon_workflow import get_product_edit, update_product_edit, update_product_edit_variant  # noqa: E402
from services.ozon_attribute_fill import (  # noqa: E402
    contains_cjk,
    enrich_variant_aspect_fields,
    listing_color_label,
    listing_size_label,
)
from services.ozon_listing_payload import collect_listing_issues  # noqa: E402


EDIT_ID = 73


def _loads(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> None:
    with get_connection(dict_cursor=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, sku, title, variant_attributes
                FROM product_edit_variant
                WHERE edit_id = %s
                ORDER BY id
                """,
                (EDIT_ID,),
            )
            rows = cur.fetchall()

    # 两套同规格灰布套撞车：按 offer 前缀区分（591788 vs 609961）
    cover_bucket_seen: dict[str, str] = {}

    for row in rows:
        raw = _loads(row.get("variant_attributes"))
        blob = " ".join(
            str(x or "")
            for x in (
                row.get("title"),
                raw.get("区分项"),
                raw.get("规格"),
                raw.get("颜色"),
                raw.get("尺码"),
            )
        )
        enriched = enrich_variant_aspect_fields({**raw, "区分项": blob or raw.get("区分项")})
        title = str(row.get("title") or "")
        sku = str(row.get("sku") or "")
        is_cover = "чехол" in title.casefold() or "布套" in blob
        color = listing_color_label(
            enriched.get("颜色"),
            enriched.get("Цвет"),
            enriched.get("Название цвета"),
            title,
            blob,
        ) or str(enriched.get("颜色") or "")
        size = listing_size_label(
            enriched.get("尺码"),
            enriched.get("Размер"),
            blob,
            title,
        )
        if is_cover:
            base = color if color and not contains_cjk(color) else "серый"
            # 去掉先前脚本加的 чехол / 序号，重新规范
            base = base.replace("чехол", "").strip()
            base = " ".join(part for part in base.split() if not part.isdigit() and part.lower() != "v2")
            base = base or "серый"
            # 同一阶数的灰布套按 offer 分段编号，避免两套 SKU 合卡撞车
            offer = sku.split("-")[-1][:6] if "-" in sku else sku[:6]
            step_key = size or "?"
            bucket_key = f"{base}|{step_key}"
            prev_offer = cover_bucket_seen.get(bucket_key)
            if prev_offer and prev_offer != offer:
                color = f"{base} чехол 2"
            else:
                color = f"{base} чехол"
                cover_bucket_seen[bucket_key] = offer
            if size and "чехол" not in size.casefold():
                size = f"чехол {size}"
        if color and not contains_cjk(color):
            # 字典色用基础色；Название цвета 保留完整区分名
            base_color = color.split()[0]
            if color.startswith("тёмно-серый") or color.startswith("темно-серый"):
                base_color = "тёмно-серый"
            elif color.startswith("светло-серый"):
                base_color = "светло-серый"
            enriched["颜色"] = color
            enriched["Цвет"] = base_color
            enriched["Цвет товара"] = base_color
            enriched["Название цвета"] = color
            enriched["款式"] = color
        if size:
            enriched["尺码"] = size
            enriched["Размер"] = size
            enriched["Размер товара"] = size
        if color and size:
            enriched["区分项"] = f"{color} · {size}"
        update_product_edit_variant(int(row["id"]), variant_attributes=enriched)
        print(sku, "→", color, "/", size)

    attrs = dict(get_product_edit(EDIT_ID).get("attributes") or {})
    attrs["variant_aspect"] = "both"
    update_product_edit(EDIT_ID, attributes=attrs, clear_listing=True)

    edit = get_product_edit(EDIT_ID)
    issues = [
        item
        for item in collect_listing_issues(edit)
        if item.get("code") == "DUPLICATE_ASPECT_PAIR"
    ]
    print("duplicate_issues", len(issues))
    for item in issues:
        print(" ", item.get("message"))


if __name__ == "__main__":
    main()
