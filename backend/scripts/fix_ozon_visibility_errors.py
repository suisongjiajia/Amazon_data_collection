"""按 Ozon 真实拒审原因，批量修正 type 并重推「错误/待修改」商品。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.ozon_workflow import get_product_edit, reopen_product_edit, update_product_edit  # noqa: E402
from integrations.ozon_seller.client import OzonSellerClient  # noqa: E402
from services.ozon_category_tree import (  # noqa: E402
    correct_category_id_for_type,
    find_type_name,
    suggest_type_id_from_text,
)
from services.ozon_daily_fix_service import _push_stock_for_offers  # noqa: E402
from services.publish_auto_service import heal_and_republish  # noqa: E402
from services import product_edit_service  # noqa: E402

EDIT_IDS = [144, 102, 110, 118, 143, 74, 115]


def _ozon_error_blob(edit: dict) -> dict:
    client = OzonSellerClient()
    offers = [str(v.get("sku") or "") for v in (edit.get("variants") or []) if v.get("sku")]
    items_out = []
    for i in range(0, len(offers), 50):
        payload = client.get_product_info_list(offer_ids=offers[i : i + 50])
        products = payload.get("items") or (payload.get("result") or {}).get("items") or []
        for p in products:
            if not isinstance(p, dict):
                continue
            errs = p.get("errors") or []
            messages = []
            for e in errs if isinstance(errs, list) else []:
                if not isinstance(e, dict):
                    continue
                texts = e.get("texts") if isinstance(e.get("texts"), dict) else {}
                messages.append(
                    str(texts.get("message") or texts.get("description") or e.get("code") or e)
                )
            items_out.append(
                {
                    "seller_sku": p.get("offer_id"),
                    "error_code": (errs[0].get("code") if errs else "OZON_STATUS"),
                    "error_message": "; ".join(messages)[:500]
                    or str((p.get("statuses") or {}).get("status_name") or ""),
                }
            )
    joined = "; ".join(
        f"{it['seller_sku']}: {it['error_message']}" for it in items_out if it.get("error_message")
    )[:1500]
    return {
        "status": "failed",
        "error_message": joined or "Ozon visibility error",
        "items": items_out,
    }


def _fix_type(edit_id: int) -> str:
    edit = get_product_edit(edit_id)
    attrs = dict(edit.get("attributes") or {})
    old_type = attrs.get("type_id")
    title = str(edit.get("title") or "")
    desc = str(edit.get("description") or "")
    suggested = suggest_type_id_from_text(title, desc, current_type_id=old_type)
    # 楼梯标题强制楼梯类型
    blob = f"{title} {desc}".casefold()
    if any(t in blob for t in ("лестниц", "ступен", "爬梯", "пандус")) and not any(
        t in blob for t in ("домик", "автогамак")
    ):
        if str(old_type) != "95204":
            suggested = 95204
    # 窝/屋标题强制 Домик（纠正汽车吊床/渔网等错类）
    if any(t in blob for t in ("домик", "猫窝")) and str(old_type) not in {"95199", "95203"}:
        suggested = 95199

    if not suggested:
        return f"type unchanged ({old_type}={find_type_name(int(old_type)) if str(old_type).isdigit() else old_type})"

    cat, type_text, _ = correct_category_id_for_type(
        description_category_id=attrs.get("description_category_id"),
        type_id=suggested,
    )
    attrs["type_id"] = int(type_text) if type_text and str(type_text).isdigit() else suggested
    if cat and str(cat).isdigit():
        attrs["description_category_id"] = int(cat)
    # 清掉旧 Тип 字典，重建时按新 type_id 回填
    for key in list(attrs.keys()):
        if str(key).strip().lower() in {"тип", "type", "type_name"}:
            attrs.pop(key, None)
    attrs["type_name"] = find_type_name(attrs["type_id"]) or ""
    update_product_edit(edit_id, attributes=attrs, clear_listing=True)
    return f"type {old_type} -> {attrs['type_id']} ({attrs.get('type_name')})"


def main() -> None:
    for edit_id in EDIT_IDS:
        print(f"\n===== edit {edit_id} =====", flush=True)
        try:
            msg = _fix_type(edit_id)
            print(" ", msg, flush=True)
            reopen_product_edit(edit_id)
            edit = get_product_edit(edit_id)
            # 重建 listing
            built = product_edit_service.build_listing(edit_id)
            print(
                f"  build ok={built.get('ok')} saved={built.get('saved')} issues="
                f"{len([i for i in (built.get('issues') or []) if i.get('severity')=='error'])}",
                flush=True,
            )
            source = _ozon_error_blob(edit)
            result = heal_and_republish(
                edit_id,
                source_task=source,
                auto_follow=True,
                reset_attempts=True,
            )
            print(" ", result.get("message"), flush=True)
            # 顺带补库存
            offers = [str(v.get("sku") or "") for v in (get_product_edit(edit_id).get("variants") or []) if v.get("sku")]
            try:
                stock_msg = _push_stock_for_offers(offers, edit_id)
                print(" ", stock_msg, flush=True)
            except Exception as stock_exc:
                print(f"  stock skip: {stock_exc}", flush=True)
        except Exception as exc:
            print(f"  FAIL: {exc}", flush=True)


if __name__ == "__main__":
    main()
