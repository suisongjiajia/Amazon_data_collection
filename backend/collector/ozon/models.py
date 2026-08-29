from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OzonCollectionStrategy(str, Enum):
    SALES_RANK = "sales_rank"
    CATEGORY_LEADERBOARD = "category_leaderboard"
    CUSTOM_RULE = "custom_rule"
    PRODUCT_URL = "product_url"


@dataclass
class OzonProductInfo:
    product_id: str
    title: str | None = None
    brand: str | None = None
    price_text: str | None = None
    main_image_url: str | None = None
    source_url: str | None = None
    sales_rank: int | None = None
    category_id: str | None = None
    type_id: str | None = None
    category_name: str | None = None
    hot_score: float | None = None
    rating: str | None = None
    review_count: str | None = None
    variant_attributes: dict[str, str] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "productId": self.product_id,
            "title": self.title,
            "brand": self.brand,
            "price": self.price_text,
            "mainImageUrl": self.main_image_url,
            "sourceUrl": self.source_url,
            "salesRank": self.sales_rank,
            "categoryId": self.category_id,
            "typeId": self.type_id,
            "categoryName": self.category_name,
            "hotScore": self.hot_score,
            "rating": self.rating,
            "reviewCount": self.review_count,
            "variantAttributes": self.variant_attributes,
            "rawPayload": self.raw_payload,
            "collectedAt": self.collected_at.isoformat(),
        }


@dataclass
class OzonCollectConfig:
    max_pages: int = 5
    max_products: int = 200
    delay_ms: int = 800
    listing_page_delay_ms: int = 500
    timeout_seconds: int = 45
    cookie: str = ""
    impersonate: str = "edge101"

    @classmethod
    def defaults(cls) -> OzonCollectConfig:
        return cls(
            max_pages=int(os.getenv("OZON_MAX_PAGES", "5")),
            max_products=int(os.getenv("OZON_MAX_PRODUCTS", "200")),
            delay_ms=int(os.getenv("OZON_DELAY_MS", "800")),
            listing_page_delay_ms=int(os.getenv("OZON_LISTING_PAGE_DELAY_MS", "500")),
            timeout_seconds=int(os.getenv("OZON_TIMEOUT_SECONDS", "45")),
            cookie=os.getenv("OZON_COOKIE", "").strip(),
            impersonate=os.getenv("OZON_IMPERSONATE", "edge101").strip() or "edge101",
        )
