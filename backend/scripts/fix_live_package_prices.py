"""批量校正已上线商品：包装尺寸优先 → 兴远抬重量 → 重算售价 → 推 Ozon。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ozon_live_package_price_service import repair_published_edits  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    parser.add_argument("--edit", type=int, action="append", default=None)
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    result = repair_published_edits(
        edit_ids=args.edit,
        dry_run=args.dry_run,
        push=not args.no_push,
        limit=args.limit,
    )
    out = ROOT / "scripts" / "_live_package_price_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("ok", "dry_run", "push", "total", "fixed", "failed")}, ensure_ascii=False))
    print("wrote", out)


if __name__ == "__main__":
    main()
