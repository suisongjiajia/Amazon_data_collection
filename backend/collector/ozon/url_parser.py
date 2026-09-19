from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


PRODUCT_ID_IN_PATH = re.compile(r"-(\d{6,})(?:/|$|\?)", re.IGNORECASE)
PRODUCT_IN_JSON = re.compile(r"/product/[a-z0-9\-]+-\d{6,}/?", re.IGNORECASE)


class OzonUrlType(str, Enum):
    PRODUCT = "product"
    SELLER = "seller"
    CATEGORY = "category"
    SEARCH = "search"


@dataclass(frozen=True)
class OzonParseResult:
    type: OzonUrlType
    source_url: str
    page_path: str
    product_id: str | None = None
    seller_slug: str | None = None


class OzonUrlParser:
    def parse(self, raw_url: str) -> OzonParseResult:
        if not raw_url or not raw_url.strip():
            raise ValueError("URL 不能为空")

        uri = urlparse(raw_url.strip())
        host = (uri.hostname or "").lower()
        if "ozon." not in host:
            raise ValueError(f"不是有效的 Ozon 链接: {raw_url}")

        path = uri.path or "/"
        if not path.startswith("/"):
            path = f"/{path}"

        source_url = f"https://www.ozon.ru{path}"
        if uri.query:
            source_url = f"{source_url}?{uri.query}"

        lower_path = path.lower()
        if "/product/" in lower_path:
            product_id = self._extract_product_id(path)
            if not product_id:
                raise ValueError("无法从商品链接解析 product id")
            canonical_path = path.split("?")[0]
            if not canonical_path.endswith("/"):
                canonical_path += "/"
            return OzonParseResult(
                OzonUrlType.PRODUCT,
                source_url,
                canonical_path,
                product_id=product_id,
            )

        seller_match = re.search(r"/seller/([^/]+)", path, re.IGNORECASE)
        if seller_match:
            seller_slug = seller_match.group(1)
            # 店铺页默认按「流行 / Популярные」排序（sorting=score）
            listing_path = f"/seller/{seller_slug}/?sorting=score"
            return OzonParseResult(
                OzonUrlType.SELLER,
                f"https://www.ozon.ru{listing_path}",
                listing_path,
                seller_slug=seller_slug,
            )

        if "/category/" in lower_path or "/search/" in lower_path:
            url_type = OzonUrlType.SEARCH if "/search/" in lower_path else OzonUrlType.CATEGORY
            return OzonParseResult(url_type, source_url, path)

        raise ValueError(f"无法识别 Ozon 链接类型: {raw_url}")

    def _extract_product_id(self, path: str) -> str | None:
        match = PRODUCT_ID_IN_PATH.search(path)
        return match.group(1) if match else None
