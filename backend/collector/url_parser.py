from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs
from urllib.parse import urlunparse
from urllib.parse import urlparse

from collector.marketplace import build_marketplace_context
from collector.marketplace import extract_locale_prefix
from collector.models import UrlType

ASIN_IN_PATH = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.IGNORECASE)


@dataclass(frozen=True)
class ParseResult:
    type: UrlType
    host: str
    asin: str | None
    listing_url: str
    locale_prefix: str = ""
    seller_id: str | None = None

    @property
    def marketplace(self):
        return build_marketplace_context(self.host, self.locale_prefix)

    def build_product_url(self, asin: str) -> str:
        return self.marketplace.build_product_url(asin)


class AmazonUrlParser:
    def parse(self, raw_url: str) -> ParseResult:
        if not raw_url or not raw_url.strip():
            raise ValueError("URL 不能为空")

        uri = urlparse(raw_url.strip())
        host = uri.hostname
        if not host or "amazon." not in host.lower():
            raise ValueError(f"不是有效的 Amazon 链接: {raw_url}")

        locale_prefix = extract_locale_prefix(uri.path or "")
        seller_id = self._extract_seller_id(uri)
        asin = self._extract_asin_from_path(uri.path or "")
        if asin:
            marketplace = build_marketplace_context(host, locale_prefix)
            canonical_url = marketplace.build_product_url(asin)
            return ParseResult(
                UrlType.PRODUCT,
                host,
                asin,
                canonical_url,
                locale_prefix,
                seller_id,
            )

        listing_url = self._normalize_listing_url(uri)
        url_type = self._detect_listing_type(uri)
        return ParseResult(url_type, host, None, listing_url, locale_prefix, seller_id)

    def _detect_listing_type(self, uri) -> UrlType:
        path = (uri.path or "").lower()
        query = (uri.query or "").lower()

        if "/stores/" in path or "me=" in query or "seller=" in query or path.startswith("/sp"):
            return UrlType.STORE
        if path.startswith("/s") or path.startswith("/b") or "rh=" in query or "node=" in query:
            return UrlType.CATEGORY

        raise ValueError(f"无法识别 URL 类型: {uri.geturl()}")

    def _normalize_listing_url(self, uri) -> str:
        if not uri.query and uri.path:
            return f"https://{uri.hostname}{uri.path}"
        return urlunparse(
            ("https", uri.hostname, uri.path or "", uri.params, uri.query, uri.fragment)
        )

    def _extract_asin_from_path(self, path: str) -> str | None:
        match = ASIN_IN_PATH.search(path)
        if match:
            return match.group(1).upper()
        return None

    @staticmethod
    def _extract_seller_id(uri) -> str | None:
        query = parse_qs(uri.query or "")
        for key in ("me", "seller", "merchant"):
            values = query.get(key)
            if values and values[0]:
                return values[0]
        return None
