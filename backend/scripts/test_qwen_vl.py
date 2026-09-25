"""测试通义 VL 读图。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    key, value = key.strip(), value.strip().strip('"').strip("'")
    if key and key not in os.environ:
        os.environ[key] = value

from integrations.qwen_vl import QwenVLClient  # noqa: E402


def main() -> int:
    image = (
        "https://cbu01.alicdn.com/img/ibank/O1CN01krtLAU1JB0pU54yyN_!!2217978240989-0-cib.jpg"
    )
    client = QwenVLClient()
    print(f"model={client.model} base={client.base_url}")
    text = client.chat_vision(
        image_url=image,
        prompt="用中文一句话描述这是什么商品、什么颜色，不要编造未见细节。",
    )
    print(text[:500])
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
