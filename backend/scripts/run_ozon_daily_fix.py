"""手动触发 / 预览 Ozon 日修（准备销售、错误、待修改）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ozon_daily_fix_service import (  # noqa: E402
    collect_problem_products,
    run_daily_fix,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ozon daily fix for seller visibility buckets")
    parser.add_argument("--scan", action="store_true", help="只扫描不修复")
    parser.add_argument("--dry-run", action="store_true", help="走修复流程但不写/推")
    parser.add_argument("--limit", type=int, default=None, help="每个状态桶上限")
    args = parser.parse_args()

    if args.scan:
        result = collect_problem_products(max_per_bucket=args.limit)
        print(json.dumps({"counts": result["counts"], "total": result["total"]}, ensure_ascii=False, indent=2))
        return

    result = run_daily_fix(dry_run=args.dry_run, max_per_bucket=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
