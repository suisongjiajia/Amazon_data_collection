"""1688 商品图过滤：去掉图标、店招、二维码等明显非产品图。"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

# 路径上明显不是商品主图/附图
_REJECT_RE = re.compile(
    r"""
    avatar|logo|icon|\.svg(?:\?|$)|tps-\d|
    emoji|sticker|sprite|qrcode|qr[_-]?code|
    wangpu|banner|button|btn_|badge|
    search|loading|placeholder|default[_-]?img|
    watermark|/app/|/lib/|1x1\.|\.gif(?:\?|$)
    """,
    re.I | re.X,
)

_HOST_OK = re.compile(r"(alicdn|alibaba|1688|cbu\d+)", re.I)


def _normalize(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    # 去掉过小缩略尺寸，统一便于去重
    text = re.sub(r"_\d+x\d+\.(jpg|jpeg|png|webp)", r".\1", text, flags=re.I)
    return text


def is_1688_product_image(url: str) -> bool:
    text = _normalize(url)
    if not text.lower().startswith(("http://", "https://")):
        return False
    if not _HOST_OK.search(text):
        return False
    if _REJECT_RE.search(text):
        return False
    path = urlparse(text).path or ""
    if len(path) < 12:
        return False
    if not re.search(r"\.(jpe?g|png|webp)(?:$|\?)", text, re.I):
        if not re.search(r"/img/ibank|/imgextra/|/offer/", text, re.I):
            return False
    return True


def filter_1688_product_images(
    urls: Iterable[str],
    *,
    max_count: int = 12,
    prefer: Iterable[str] | None = None,
) -> list[str]:
    """
    去重并过滤非产品图。prefer（SKU 主图/列表图）优先排前。
    默认最多 12 张，避免详情装饰图灌爆图集。
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        url = _normalize(raw)
        if not url or url in seen or not is_1688_product_image(url):
            return
        seen.add(url)
        ordered.append(url)

    for raw in prefer or []:
        _add(str(raw or ""))
    for raw in urls:
        if len(ordered) >= max_count:
            break
        _add(str(raw or ""))
    return ordered[:max_count]
