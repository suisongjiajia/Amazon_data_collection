"""清空数据、删除废弃表、补齐表注释。

用法（项目根目录）:
  .python\\python.exe backend/scripts/reset_database.py
  .python\\python.exe backend/scripts/reset_database.py --full   # 删表重建
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: F401  # load .env
from db.schema import (
    ACTIVE_TABLES,
    apply_table_comments,
    clear_all_data,
    drop_legacy_tables,
    init_db,
    reset_db,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="重置数据库：清数据 / 删废弃表 / 表注释")
    parser.add_argument(
        "--full",
        action="store_true",
        help="删表并重建（会清空结构后重新创建）",
    )
    args = parser.parse_args()

    if args.full:
        print("正在删表重建...")
        reset_db()
    else:
        print("正在清空所有表数据...")
        clear_all_data()
        print("正在删除废弃表...")
        drop_legacy_tables()
        print("正在确保当前表结构...")
        init_db()

    apply_table_comments()
    print(f"完成。当前业务表 {len(ACTIVE_TABLES)} 张：")
    for name in ACTIVE_TABLES:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
