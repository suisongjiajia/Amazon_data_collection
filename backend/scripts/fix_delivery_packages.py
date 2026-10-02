"""
修复已上架商品的配送尺寸/重量错误：
- 椭圆窝等把商品展开尺寸当成包装 → 体积重虚高
- 多尺码共用同一套包装

按标题里的尺码写入变体级包装，再 /v3/product/import 更新 Ozon。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.connection import get_connection  # noqa: E402
from db.ozon_workflow import get_product_edit, update_product_edit, update_product_edit_variant  # noqa: E402
from integrations.ozon_seller.client import OzonSellerClient  # noqa: E402
from services.ozon_import_status import extract_import_task_id  # noqa: E402
from services.ozon_listing_payload import build_import_items, read_variant_package_metrics  # noqa: E402


EDIT_IDS = (105, 114, 152, 153)


def _loads(value: Any) -> dict[str, Any]:
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


def _product_cm_from_text(*texts: Any) -> tuple[int, int] | None:
    blob = " ".join(str(t or "") for t in texts)
    matched = re.search(
        r"(\d{2,3})\s*[x×х*]\s*(\d{2,3})(?:\s*[x×х*]\s*(\d{2,3}))?",
        blob,
        flags=re.I,
    )
    if not matched:
        return None
    a, b = int(matched.group(1)), int(matched.group(2))
    # 毫米误写成厘米的情况（>200）
    if a > 200 or b > 200:
        a, b = max(1, round(a / 10)), max(1, round(b / 10))
    return a, b


def _size_letter(*texts: Any) -> str | None:
    blob = " ".join(str(t or "") for t in texts)
    upper = blob.upper()
    for letter in ("XXL", "XL", "XS", "XXS", "S", "M", "L"):
        if re.search(rf"(?:^|[^A-Z0-9]){letter}(?:[^A-Z0-9]|$)", upper):
            return letter
    lower = blob.lower()
    if "средн" in lower:
        return "M"
    if "малы" in lower or "маленьк" in lower:
        return "S"
    if "больш" in lower:
        return "L"
    return None


def _package_for(edit_id: int, title: str, sku: str) -> tuple[int, int, int, int]:
    """返回 depth,width,height mm + weight g（压缩后的可寄送包装）。"""
    cm = _product_cm_from_text(title, sku)
    letter = _size_letter(title, sku)
    long_cm = max(cm) if cm else None

    # 藤编凉席：偏扁硬包
    if edit_id == 152:
        if long_cm and long_cm <= 42:
            return 350, 250, 80, 380
        if long_cm and long_cm <= 52:
            return 420, 300, 90, 480
        return 500, 350, 100, 580

    # 半封闭窝屋：可压扁但厚一点
    if edit_id == 114:
        if letter in {"XS", "S"} or (long_cm and long_cm <= 42):
            return 400, 320, 110, 550
        if letter == "M" or (long_cm and long_cm <= 50):
            return 450, 360, 120, 750
        if letter == "L" or (long_cm and long_cm <= 58):
            return 500, 400, 130, 950
        return 520, 420, 140, 1150

    # 冬季软垫 / 椭圆窝：真空压缩软包
    if letter in {"XS", "S"} or (long_cm and long_cm <= 45):
        return 380, 280, 80, 420
    if letter == "M" or (long_cm and long_cm <= 55):
        return 450, 340, 90, 620
    if letter == "L" or (long_cm and long_cm <= 70):
        return 520, 400, 100, 900
    # XL / 70x100
    return 560, 450, 110, 1150


def _write_package(va: dict[str, Any], depth: int, width: int, height: int, weight: int) -> dict[str, Any]:
    out = dict(va)
    out["depth_mm"] = str(depth)
    out["width_mm"] = str(width)
    out["height_mm"] = str(height)
    out["length_mm"] = str(depth)
    out["weight_g"] = str(weight)
    out["Длина, мм"] = str(depth)
    out["Ширина, мм"] = str(width)
    out["Высота, мм"] = str(height)
    out["Вес, г"] = str(weight)
    out["Вес товара, г"] = str(weight)
    out["Вес с упаковкой, г"] = str(weight)
    out["Размер упаковки (Длина х Ширина х Высота), см"] = (
        f"{max(1, round(depth / 10))}x{max(1, round(width / 10))}x{max(1, round(height / 10))}"
    )
    return out


def repair_edit(edit_id: int) -> dict[str, Any]:
    with get_connection(dict_cursor=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, sku, title, variant_attributes
                FROM product_edit_variant
                WHERE edit_id = %s
                ORDER BY id
                """,
                (edit_id,),
            )
            variants = cur.fetchall()

    updated = []
    for row in variants:
        sku = str(row["sku"])
        title = str(row["title"] or "")
        depth, width, height, weight = _package_for(edit_id, title, sku)
        va = _loads(row.get("variant_attributes"))
        new_va = _write_package(va, depth, width, height, weight)
        update_product_edit_variant(int(row["id"]), variant_attributes=new_va)
        updated.append(
            {
                "sku": sku,
                "title": title[:48],
                "package_mm": [depth, width, height],
                "weight_g": weight,
                "vw": round((depth * width * height) / 1000 / 5000, 2),
            }
        )

    # 商品级也改成中位包装，避免无变体字段时回落爆仓
    mid = updated[len(updated) // 2] if updated else None
    if mid:
        d, w, h = mid["package_mm"]
        wt = mid["weight_g"]
        edit = get_product_edit(edit_id)
        attrs = dict(edit.get("attributes") or {})
        attrs.update(
            {
                "package_manual": "1",
                "package_source": "delivery_fix_script",
                "Длина, мм": str(d),
                "Ширина, мм": str(w),
                "Высота, мм": str(h),
                "Вес, г": str(wt),
                "Вес товара, г": str(wt),
                "Вес с упаковкой, г": str(wt),
                "depth_mm": str(d),
                "width_mm": str(w),
                "height_mm": str(h),
                "weight_g": str(wt),
            }
        )
        update_product_edit(edit_id, attributes=attrs, clear_listing=True)

    return {"edit_id": edit_id, "variants": updated}


def push_edit(edit_id: int) -> dict[str, Any]:
    edit = get_product_edit(edit_id)
    # 校验变体包装已按尺码区分
    seen = set()
    for variant in edit.get("variants") or []:
        metrics = read_variant_package_metrics(edit.get("attributes") or {}, variant)
        seen.add(metrics)
        print("  check", variant.get("sku"), metrics)
    if len(seen) < 2 and len(edit.get("variants") or []) > 2:
        print("WARN: few distinct packages for edit", edit_id)

    items = build_import_items(edit)
    client = OzonSellerClient()

    # 已上架商品：锁定 Ozon 现有 category/type，避免 suggest_type 改成 Домик 导致尺寸更新失败
    offer_ids = [str(it.get("offer_id") or "") for it in items if it.get("offer_id")]
    live_by_offer: dict[str, dict[str, Any]] = {}
    for i in range(0, len(offer_ids), 50):
        chunk = offer_ids[i : i + 50]
        try:
            data = client.request(
                "POST",
                "/v4/product/info/attributes",
                {
                    "filter": {"offer_id": chunk, "product_id": [], "sku": []},
                    "limit": 100,
                    "sort_dir": "ASC",
                },
            )
        except Exception as exc:
            print("  live attrs fetch fail", exc)
            continue
        for row in data.get("result") or []:
            oid = str(row.get("offer_id") or "")
            if oid:
                live_by_offer[oid] = row

    locked = 0
    for item in items:
        oid = str(item.get("offer_id") or "")
        live = live_by_offer.get(oid) or {}
        live_type = live.get("type_id")
        live_cat = live.get("description_category_id")
        if live_type:
            item["type_id"] = int(live_type)
            locked += 1
        if live_cat:
            item["description_category_id"] = int(live_cat)
    print("  locked type/cat from live", locked, "/", len(items))

    task_ids = []
    for i in range(0, len(items), 20):
        chunk = items[i : i + 20]
        resp = client.import_products(chunk)
        tid = extract_import_task_id(resp)
        task_ids.append(tid)
        print("  import batch", i, "task", tid, "n", len(chunk))
        time.sleep(1.5)
    return {"edit_id": edit_id, "task_ids": task_ids, "item_count": len(items)}


def main() -> None:
    args = [a for a in sys.argv[1:] if not str(a).startswith("--")]
    push = "--no-push" not in sys.argv
    edit_ids = [int(x) for x in args] or list(EDIT_IDS)
    results = []
    for edit_id in edit_ids:
        print("=== repair", edit_id, "===")
        info = repair_edit(edit_id)
        for row in info["variants"]:
            print(
                " ",
                row["sku"],
                row["package_mm"],
                row["weight_g"],
                "vw",
                row["vw"],
                row["title"],
            )
        if push:
            print("=== push", edit_id, "===")
            pushed = push_edit(edit_id)
            info["push"] = pushed
            print("  tasks", pushed["task_ids"])
        results.append(info)
    out = ROOT / "scripts" / "_delivery_fix_result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
