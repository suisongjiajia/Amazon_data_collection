from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, urlparse


class Alibaba1688UrlType(str, Enum):
    OFFER = "offer"
    SHOP = "shop"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Alibaba1688ParsedUrl:
    type: Alibaba1688UrlType
    source_url: str
    offer_id: str | None = None
    shop_host: str | None = None


_OFFER_RE = re.compile(r"(?:detail\.1688\.com/offer/|offer/)(\d{6,})", re.I)
_SHOP_HOST_RE = re.compile(
    r"^(?:[\w-]+\.)?1688\.com$|^(?:[\w-]+\.)?alibaba\.com$",
    re.I,
)


class Alibaba1688UrlParser:
    def parse(self, raw_url: str) -> Alibaba1688ParsedUrl:
        text = str(raw_url or "").strip()
        if not text:
            raise ValueError("请粘贴 1688 链接")
        if not re.match(r"^https?://", text, re.I):
            text = "https://" + text.lstrip("/")

        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        query = parse_qs(parsed.query)

        offer_match = _OFFER_RE.search(text)
        if offer_match:
            offer_id = offer_match.group(1)
            return Alibaba1688ParsedUrl(
                type=Alibaba1688UrlType.OFFER,
                source_url=f"https://detail.1688.com/offer/{offer_id}.html",
                offer_id=offer_id,
            )

        # 店铺常见形态：xxx.1688.com / shop.1688.com / winport / page/offerlist
        is_1688 = "1688.com" in host or "alibaba.com" in host
        shop_signals = (
            "offerlist" in path.lower()
            or "winport" in path.lower()
            or "shop" in host
            or bool(query.get("memberId"))
            or bool(query.get("memberid"))
            or (is_1688 and host.count(".") >= 2 and "detail." not in host and "air." not in host)
        )
        if is_1688 and shop_signals:
            # 去掉追踪参数，保留可打开的店铺地址
            clean = f"{parsed.scheme}://{parsed.netloc}{path}"
            if parsed.query and ("memberId" in parsed.query or "memberid" in parsed.query):
                clean = f"{clean}?{parsed.query}"
            return Alibaba1688ParsedUrl(
                type=Alibaba1688UrlType.SHOP,
                source_url=clean.rstrip("?") or text,
                shop_host=host,
            )

        if is_1688 and _SHOP_HOST_RE.match(host or ""):
            # 根域名店铺页也当店铺处理
            if "detail." not in host and "air." not in host and "login." not in host:
                return Alibaba1688ParsedUrl(
                    type=Alibaba1688UrlType.SHOP,
                    source_url=f"{parsed.scheme}://{parsed.netloc}{path or '/'}",
                    shop_host=host,
                )

        raise ValueError(
            "无法识别为 1688 店铺或商品链接。请粘贴如 https://shopXXXX.1688.com/ "
            "或 https://detail.1688.com/offer/123.html"
        )


def is_1688_shop_url(url: str) -> bool:
    try:
        return Alibaba1688UrlParser().parse(url).type is Alibaba1688UrlType.SHOP
    except ValueError:
        return False


def is_1688_url(url: str) -> bool:
    text = str(url or "").lower()
    return "1688.com" in text or "alibaba.com" in text
