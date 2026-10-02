"""归档同账号 SPU 重复卡（类似商品在个人中心重复）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.ozon_workflow import get_product_edit  # noqa: E402
from integrations.ozon_seller.client import OzonSellerClient  # noqa: E402
from services.ozon_daily_fix_service import collect_problem_products  # noqa: E402
from services.ozon_spu_duplicate_service import (  # noqa: E402
    fetch_products_by_offers,
    resolve_spu_duplicates,
    resolve_spu_duplicates_for_edit,
)

DEFAULT_EDIT_IDS = [144, 102, 110, 118, 143, 74, 115]


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive same-account Ozon SPU duplicates")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--edit", type=int, action="append", default=None, help="指定 edit_id，可多次")
    parser.add_argument("--from-visibility", action="store_true", help="从错误/待修改可见性桶扫描")
    parser.add_argument("--limit", type=int, default=120)
    args = parser.parse_args()

    if args.from_visibility:
        scanned = collect_problem_products(max_per_bucket=args.limit)
        offers: list[str] = []
        for rows in (scanned.get("buckets") or {}).values():
            for row in rows or []:
                offer = str(row.get("offer_id") or "").strip()
                if offer:
                    offers.append(offer)
        # details 里也可能带 offer
        for product in (scanned.get("products") or []):
            if isinstance(product, dict) and product.get("offer_id"):
                offers.append(str(product["offer_id"]).strip())
        offers = list(dict.fromkeys(offers))
        print(f"visibility offers={len(offers)}", flush=True)
        result = resolve_spu_duplicates(offer_ids=offers, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    edit_ids = args.edit or DEFAULT_EDIT_IDS
    client = OzonSellerClient()
    all_offers: list[str] = []
    for edit_id in edit_ids:
        edit = get_product_edit(edit_id)
        for v in edit.get("variants") or []:
            sku = str(v.get("sku") or "").strip()
            if sku:
                all_offers.append(sku)
    all_offers = list(dict.fromkeys(all_offers))
    products = fetch_products_by_offers(client, all_offers)
    # 补齐报错引用的 keeper
    from services.ozon_spu_duplicate_service import (
        is_same_account_spu_duplicate,
        parse_duplicate_offer_ids,
        _offer_id,
    )

    extra: list[str] = []
    known = {_offer_id(p) for p in products}
    for p in products:
        if is_same_account_spu_duplicate(p, company_id=client.client_id):
            for ref in parse_duplicate_offer_ids(p):
                if ref not in known:
                    extra.append(ref)
    if extra:
        products.extend(fetch_products_by_offers(client, list(dict.fromkeys(extra))))

    batch = resolve_spu_duplicates(products=products, dry_run=args.dry_run, client=client)
    print(json.dumps(batch, ensure_ascii=False, indent=2, default=str))
    if not args.dry_run:
        for edit_id in edit_ids:
            # 写 last_spu_archive 标记
            note = resolve_spu_duplicates_for_edit(edit_id, dry_run=True)
            if int(note.get("archive_count") or 0) == 0 and int(batch.get("archive_count") or 0) > 0:
                from db.ozon_workflow import update_product_edit

                attrs = dict(get_product_edit(edit_id).get("attributes") or {})
                attrs["last_spu_archive"] = batch.get("message") or ""
                update_product_edit(edit_id, attributes=attrs, clear_listing=True)


if __name__ == "__main__":
    main()
