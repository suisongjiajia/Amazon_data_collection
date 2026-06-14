from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from datetime import datetime
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urljoin
from urllib.parse import urlparse
from urllib.parse import urlunparse

import requests
from bs4 import BeautifulSoup
from bs4 import Tag

from collector.marketplace import MarketplaceContext
from collector.models import CollectConfig, ProductInfo, UrlType
from collector.url_parser import AmazonUrlParser, ParseResult
from collector.variant_parser import VariantOption, parse_variants

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ASIN_IN_LINK = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.IGNORECASE)


class AmazonCollector:
    def __init__(self, config: CollectConfig | None = None) -> None:
        self.url_parser = AmazonUrlParser()
        self.config = config or CollectConfig.defaults()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Cache-Control": "no-cache",
            }
        )
        self._marketplace: MarketplaceContext | None = None

    def collect(self, url: str) -> list[ProductInfo]:
        parsed = self.url_parser.parse(url)
        self._prepare_session(parsed)
        if parsed.type is UrlType.PRODUCT:
            return self.collect_product_variants(parsed)
        return self.collect_from_listing(parsed)

    def _prepare_session(self, parsed: ParseResult) -> None:
        marketplace = parsed.marketplace
        self._marketplace = marketplace
        self.session.headers["Accept-Language"] = marketplace.accept_language

        try:
            self.session.get(marketplace.build_home_url(), timeout=(15, 30))
        except requests.RequestException:
            pass

        for name, value in marketplace.cookie_items().items():
            self.session.cookies.set(name, value, domain=marketplace.cookie_domain)

    def collect_product_variants(self, parsed: ParseResult) -> list[ProductInfo]:
        if not parsed.asin:
            raise ValueError("商品 URL 缺少 ASIN")

        html = self._fetch(parsed.listing_url, parsed)
        doc = BeautifulSoup(html, "html.parser")
        shared = self._extract_shared_product_fields(doc)
        variants = self._extract_variant_options(doc, html, parsed.asin)

        if len(variants) <= 1:
            variant = variants[0] if variants else VariantOption(asin=parsed.asin)
            return [self._build_product_info(doc, parsed, variant, shared)]

        results: list[ProductInfo] = []
        for index, variant in enumerate(variants):
            if variant.asin == parsed.asin:
                variant_doc = doc
            else:
                if index > 0:
                    self._sleep(self.config.delay_ms)
                variant_doc = self._fetch_document(parsed.build_product_url(variant.asin), parsed)
            results.append(self._build_product_info(variant_doc, parsed, variant, shared))
        return results

    def collect_product(self, parsed: ParseResult) -> ProductInfo:
        if not parsed.asin:
            raise ValueError("商品 URL 缺少 ASIN")
        return self.collect_product_variants(parsed)[0]

    def collect_from_listing(self, parsed: ParseResult) -> list[ProductInfo]:
        asins = self._discover_asins(parsed)[: self.config.max_products]
        if not asins:
            return []

        if self.config.concurrency <= 1:
            return self._collect_listing_sequential(asins, parsed)
        return self._collect_listing_parallel(asins, parsed)

    def _collect_listing_sequential(self, asins: list[str], parsed: ParseResult) -> list[ProductInfo]:
        results: list[ProductInfo] = []
        for index, asin in enumerate(asins):
            product = self._collect_product_by_asin(asin, parsed)
            if product is not None:
                results.append(product)
            if index < len(asins) - 1:
                self._sleep(self.config.delay_ms)
        return results

    def _collect_listing_parallel(self, asins: list[str], parsed: ParseResult) -> list[ProductInfo]:
        workers = min(max(1, self.config.concurrency), len(asins))
        ordered: dict[str, ProductInfo] = {}

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self._collect_product_by_asin, asin, parsed, self._clone_session()): asin
                for asin in asins
            }
            for future in as_completed(futures):
                product = future.result()
                if product is not None:
                    ordered[product.asin] = product

        return [ordered[asin] for asin in asins if asin in ordered]

    def _collect_product_by_asin(
        self,
        asin: str,
        parsed: ParseResult,
        session: requests.Session | None = None,
    ) -> ProductInfo | None:
        try:
            doc = self._fetch_document(parsed.build_product_url(asin), parsed, session)
        except RuntimeError:
            return None

        shared = self._extract_shared_product_fields(doc)
        return self._build_product_info(
            doc,
            parsed,
            VariantOption(asin=asin),
            shared,
        )

    def _extract_shared_product_fields(self, doc: BeautifulSoup) -> dict[str, object]:
        return {
            "title": self._extract_title(doc),
            "rating": self._extract_rating(doc),
            "review_count": self._extract_review_count(doc),
            "brand": self._extract_brand(doc),
            "bullet_points": self._extract_bullets(doc),
        }

    def _build_product_info(
        self,
        doc: BeautifulSoup,
        parsed: ParseResult,
        variant: VariantOption,
        shared: dict[str, object],
    ) -> ProductInfo:
        product_url = parsed.build_product_url(variant.asin)
        return ProductInfo(
            asin=variant.asin,
            source_url=product_url,
            title=shared.get("title"),  # type: ignore[arg-type]
            price=self._extract_price(doc),
            rating=shared.get("rating"),  # type: ignore[arg-type]
            review_count=shared.get("review_count"),  # type: ignore[arg-type]
            main_image_url=self._extract_main_image(doc),
            brand=shared.get("brand"),  # type: ignore[arg-type]
            size=variant.size,
            color=variant.color,
            variant_attributes=dict(variant.attributes),
            bullet_points=shared.get("bullet_points") or [],  # type: ignore[arg-type]
            collected_at=datetime.now(),
        )

    def _extract_variant_options(
        self,
        doc: BeautifulSoup,
        html: str,
        fallback_asin: str,
    ) -> list[VariantOption]:
        return parse_variants(html, doc, fallback_asin)

    def _discover_asins(self, parsed: ParseResult) -> list[str]:
        asins: list[str] = []
        seen: set[str] = set()
        next_url: str | None = parsed.listing_url

        for page in range(1, self.config.max_pages + 1):
            if not next_url:
                break

            doc = self._fetch_document(next_url, parsed)
            page_asins = self._extract_asins_from_listing(doc)
            for asin in page_asins:
                if asin not in seen:
                    seen.add(asin)
                    asins.append(asin)
                if len(asins) >= self.config.max_products:
                    return asins

            if not page_asins:
                break

            next_url = self._find_next_page_url(doc, next_url)
            if next_url and page < self.config.max_pages:
                self._sleep(self.config.listing_page_delay_ms)

        return asins

    def _extract_asins_from_listing(self, doc: BeautifulSoup) -> list[str]:
        asins: list[str] = []
        seen: set[str] = set()
        elements = self._select_listing_items(doc)

        for element in elements:
            if self._is_sponsored_result(element):
                continue

            asin = element.get("data-asin", "").strip().upper()
            if self._is_valid_asin(asin) and asin not in seen:
                seen.add(asin)
                asins.append(asin)

        if asins:
            return asins

        for link in doc.select('div.s-main-slot a[href*="/dp/"], div.s-main-slot a[href*="/gp/product/"]'):
            if self._is_sponsored_result(link):
                continue
            href = link.get("href", "")
            match = ASIN_IN_LINK.search(href)
            if match:
                asin = match.group(1).upper()
                if self._is_valid_asin(asin) and asin not in seen:
                    seen.add(asin)
                    asins.append(asin)

        return asins

    def _select_listing_items(self, doc: BeautifulSoup) -> list[Tag]:
        scoped_selectors = [
            'div.s-main-slot div[data-component-type="s-search-result"][data-asin]',
            'div.s-main-slot div.s-result-item[data-asin]',
            'div[data-component-type="s-search-results"] div[data-asin]',
            'div.s-main-slot [data-asin]',
        ]
        for selector in scoped_selectors:
            elements = doc.select(selector)
            if elements:
                return elements

        store_selectors = [
            'div[class*="store"] [data-asin]',
            'div[data-testid="store-product-grid"] [data-asin]',
        ]
        for selector in store_selectors:
            elements = doc.select(selector)
            if elements:
                return elements

        return []

    @staticmethod
    def _is_sponsored_result(element: Tag) -> bool:
        for parent in element.parents:
            if not getattr(parent, "name", None):
                continue
            component_type = parent.get("data-component-type", "")
            if component_type == "sp-sponsored-result":
                return True
            class_list = parent.get("class") or []
            if any("AdHolder" in class_name or "puis-sponsored" in class_name for class_name in class_list):
                return True
        return False

    def _find_next_page_url(self, doc: BeautifulSoup, current_url: str) -> str | None:
        next_button = doc.select_one("a.s-pagination-next:not(.s-pagination-disabled)")
        if next_button:
            href = next_button.get("href", "").strip()
            if href:
                return urljoin(current_url, href)

        parsed = urlparse(current_url)
        if "s?" not in current_url and "/s" not in parsed.path:
            return None

        query = parse_qs(parsed.query, keep_blank_values=True)
        current_page = int(query.get("page", ["1"])[0])
        page_numbers: list[int] = []
        for item in doc.select(".s-pagination-item"):
            text = item.get_text(strip=True)
            if text.isdigit():
                page_numbers.append(int(text))

        if not page_numbers or current_page >= max(page_numbers):
            return None

        if not doc.select('[data-component-type="s-search-result"]'):
            return None

        query["page"] = [str(current_page + 1)]
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    def _fetch_document(
        self,
        url: str,
        parsed: ParseResult,
        session: requests.Session | None = None,
    ) -> BeautifulSoup:
        html = self._fetch(url, parsed, session)
        return BeautifulSoup(html, "html.parser")

    def _fetch(
        self,
        url: str,
        parsed: ParseResult,
        session: requests.Session | None = None,
    ) -> str:
        active_session = session or self.session
        if session is None and self._marketplace is None:
            self._prepare_session(parsed)

        try:
            response = active_session.get(url, timeout=(15, 30))
        except requests.RequestException as exc:
            raise RuntimeError(f"网络错误: {url}") from exc

        if not response.ok:
            raise RuntimeError(f"请求失败 HTTP {response.status_code}: {url}")
        return response.text

    def _clone_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update(dict(self.session.headers))
        session.cookies.update(self.session.cookies)
        return session

    def _extract_title(self, doc: BeautifulSoup) -> str | None:
        element = doc.select_one("#productTitle")
        return element.get_text(strip=True) if element else None

    def _extract_price(self, doc: BeautifulSoup) -> str | None:
        selectors = [
            "#corePrice_feature_div .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            "#tp_price_block_total_price_ww .a-offscreen",
            ".priceToPay .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "span[data-a-color='price'] .a-offscreen",
            ".a-price .a-offscreen",
        ]
        for selector in selectors:
            element = doc.select_one(selector)
            if element is None:
                continue
            text = element.get_text(strip=True)
            if text:
                return text
        return None

    def _extract_rating(self, doc: BeautifulSoup) -> str | None:
        element = self._first_non_null(
            doc.select_one("#acrPopover span.a-icon-alt"),
            doc.select_one("[data-hook=rating-out-of-text]"),
        )
        return element.get_text(strip=True) if element else None

    def _extract_review_count(self, doc: BeautifulSoup) -> str | None:
        element = doc.select_one("#acrCustomerReviewText")
        return element.get_text(strip=True) if element else None

    def _extract_main_image(self, doc: BeautifulSoup) -> str | None:
        element = doc.select_one("#landingImage")
        if not element:
            return None
        hi_res = element.get("data-old-hires", "").strip()
        return hi_res or element.get("src")

    def _extract_brand(self, doc: BeautifulSoup) -> str | None:
        element = doc.select_one("#bylineInfo")
        return element.get_text(strip=True) if element else None

    def _extract_bullets(self, doc: BeautifulSoup) -> list[str]:
        selectors = [
            "#feature-bullets li span.a-list-item",
            "#featurebullets_feature_div li span.a-list-item",
            "#featurebullets_feature_div li",
            "#productFactsDesktopExpander li",
        ]

        for selector in selectors:
            bullets: list[str] = []
            seen: set[str] = set()
            for item in doc.select(selector):
                text = item.get_text(strip=True)
                if self._is_valid_bullet(text, seen):
                    seen.add(text)
                    bullets.append(text)
            if bullets:
                return bullets
        return []

    @staticmethod
    def _is_valid_bullet(text: str, seen: set[str]) -> bool:
        if not text or text in seen:
            return False
        lowered = text.lower()
        if lowered.startswith("make sure this fits"):
            return False
        if "product details" in lowered and lowered.startswith("see "):
            return False
        return True

    @staticmethod
    def _first_non_null(*elements: Tag | None) -> Tag | None:
        for element in elements:
            if element is not None:
                return element
        return None

    @staticmethod
    def _is_valid_asin(asin: str) -> bool:
        return bool(asin) and bool(re.fullmatch(r"[A-Z0-9]{10}", asin))

    @staticmethod
    def _sleep(millis: int) -> None:
        if millis <= 0:
            return
        time.sleep(millis / 1000)
