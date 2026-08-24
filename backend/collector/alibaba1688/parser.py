from __future__ import annotations

from typing import Any


def parse_supplier_candidates(offers: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for offer in offers[:limit]:
        if not isinstance(offer, dict):
            continue
        price = offer.get("price")
        price_text = f"¥{price}" if price else None
        normalization = offer.get("normalizationScore")
        match_score: float | None = None
        if normalization is not None:
            try:
                match_score = round(float(normalization) * 100, 2)
            except (TypeError, ValueError):
                match_score = None

        candidates.append(
            {
                "supplier_name": offer.get("companyName"),
                "shop_name": offer.get("companyName"),
                "product_title": offer.get("title") or offer.get("translateTitle"),
                "product_url": offer.get("link"),
                "image_url": offer.get("imageUrl"),
                "price_text": price_text,
                "min_order_qty": offer.get("monthSold"),
                "match_score": match_score,
                "status": "candidate",
                "raw_payload": offer,
            }
        )
    return candidates
