"""
连通性测试：通义 qwen-image-3.0 文生图（可选图生图）。

用法（在项目根目录）:
  .\\.python\\python.exe backend\\scripts\\test_qwen_image.py
  .\\.python\\python.exe backend\\scripts\\test_qwen_image.py --image https://...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# 加载 .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="测试 qwen-image-3.0")
    parser.add_argument(
        "--prompt",
        default=(
            "电商产品主图，灰色加绒宠物窝，白底，无文字无水印无Logo，"
            "正方形构图，光线柔和，真实摄影风格"
        ),
    )
    parser.add_argument("--image", default="", help="可选：原图 URL，走图生图/编辑")
    parser.add_argument("--extend", action="store_true", help="开启 prompt_extend")
    parser.add_argument("--out", default="", help="把原始 JSON 写到文件")
    args = parser.parse_args()

    from integrations.qwen_image import QwenImageClient, QwenImageError

    client = QwenImageClient()
    print(f"base={client.base_url}")
    print(f"model={client.model}")
    print(f"key_set={bool(client.api_key)} key_suffix=...{(client.api_key[-4:] if client.api_key else '')}")
    print(f"prompt={args.prompt[:80]}...")
    if args.image:
        print(f"image={args.image}")

    try:
        result = client.generate(
            args.prompt,
            image_url=args.image or None,
            prompt_extend=bool(args.extend),
            negative_prompt="text, watermark, chinese characters, logo, blurry",
        )
    except QwenImageError as exc:
        print(f"FAIL: {exc}")
        return 1

    images = result.get("images") or []
    print(f"request_id={result.get('request_id')}")
    print(f"images_count={len(images)}")
    for index, url in enumerate(images, 1):
        print(f"  [{index}] {url}")

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(result.get("raw"), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"raw -> {out_path}")

    if not images:
        print("WARN: 未解析到图片 URL，打印 raw 摘要：")
        raw = result.get("raw")
        print(json.dumps(raw, ensure_ascii=False)[:1200])
        return 2

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
