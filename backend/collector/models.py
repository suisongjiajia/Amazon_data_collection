from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class UrlType(Enum):
    PRODUCT = "PRODUCT"
    STORE = "STORE"
    CATEGORY = "CATEGORY"


@dataclass
class CollectConfig:
    max_pages: int = 20
    max_products: int = 200
    delay_ms: int = 3000
    listing_page_delay_ms: int = 500
    concurrency: int = 5

    @classmethod
    def defaults(cls) -> CollectConfig:
        return cls(
            max_pages=int(os.getenv("COLLECT_MAX_PAGES", "20")),
            max_products=int(os.getenv("COLLECT_MAX_PRODUCTS", "200")),
            delay_ms=int(os.getenv("COLLECT_DELAY_MS", "3000")),
            listing_page_delay_ms=int(os.getenv("COLLECT_LISTING_PAGE_DELAY_MS", "500")),
            concurrency=int(os.getenv("COLLECT_CONCURRENCY", "5")),
        )


@dataclass
class ProductInfo:
    asin: str | None = None
    source_url: str | None = None
    title: str | None = None
    price: str | None = None
    rating: str | None = None
    review_count: str | None = None
    main_image_url: str | None = None
    brand: str | None = None
    size: str | None = None
    color: str | None = None
    variant_attributes: dict[str, str] = field(default_factory=dict)
    family_key: str | None = None
    family_variant_asins: list[str] = field(default_factory=list)
    bullet_points: list[str] = field(default_factory=list)
    collected_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "asin": self.asin,
            "sourceUrl": self.source_url,
            "title": self.title,
            "price": self.price,
            "rating": self.rating,
            "reviewCount": self.review_count,
            "mainImageUrl": self.main_image_url,
            "brand": self.brand,
            "size": self.size,
            "color": self.color,
            "variantAttributes": self.variant_attributes or None,
            "familyKey": self.family_key,
            "familyVariantAsins": self.family_variant_asins or None,
            "bulletPoints": self.bullet_points or None,
            "collectedAt": self.collected_at.isoformat() if self.collected_at else None,
        }
        return {key: value for key, value in data.items() if value is not None}
