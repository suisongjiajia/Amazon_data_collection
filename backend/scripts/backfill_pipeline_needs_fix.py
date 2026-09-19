from __future__ import annotations

from db.ozon_workflow import get_product_edit, update_product_edit
from db.serialization import fetch_all
from db.shop_pipeline import recount_pipeline_job, update_pipeline_item
from services.product_edit_service import create_edit
from services.shop_pipeline_service import classify_pipeline_error

items = fetch_all(
    """
    SELECT id, job_id, edit_id, status, error_message, raw_product_family_id
    FROM shop_pipeline_item
    WHERE status IN ('failed', 'attr_missing', 'image_failed', 'sourcing_failed',
                     'listing_failed', 'pipeline_failed')
       OR (error_message IS NOT NULL AND error_message != '' AND status NOT IN
           ('pending_review', 'published', 'publishing', 'approved', 'queued',
            'sourcing', 'editing', 'listing', 'collecting', 'processing'))
    """,
    (),
)

fixed = 0
jobs: set[int] = set()
for item in items:
    err = str(item.get("error_message") or "").strip()
    if not err and item.get("status") == "failed":
        err = "处理失败"
    if not err:
        continue
    kind = classify_pipeline_error(err)
    edit_id = item.get("edit_id")
    try:
        if edit_id:
            edit = get_product_edit(int(edit_id))
            if edit.get("status") in {"pending_review", "approved", "published"}:
                update_pipeline_item(int(item["id"]), status=kind)
                jobs.add(int(item["job_id"]))
                fixed += 1
                continue
        else:
            edit = create_edit(int(item["raw_product_family_id"]))
            edit_id = int(edit["id"])
            edit = get_product_edit(int(edit_id))
        attrs = dict(edit.get("attributes") or {})
        attrs["pipeline_error"] = err[:2000]
        attrs["failure_kind"] = kind
        update_product_edit(int(edit_id), attributes=attrs, status="needs_fix")
        update_pipeline_item(int(item["id"]), status=kind, edit_id=int(edit_id))
        jobs.add(int(item["job_id"]))
        fixed += 1
    except Exception as exc:
        print("skip", item["id"], exc)

print("fixed", fixed, "jobs", sorted(jobs))
for job_id in jobs:
    recount_pipeline_job(job_id)
