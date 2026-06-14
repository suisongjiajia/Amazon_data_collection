from datetime import datetime

from fastapi.testclient import TestClient

import api
import main
from services import collection_service
from collector.models import ProductInfo


class StubCollector:
    def collect(self, url: str) -> list[ProductInfo]:
        return [
            ProductInfo(
                asin="B0TESTASIN",
                source_url=url,
                title="Example product",
                price="$19.99",
                rating="4.8 out of 5 stars",
                review_count="128",
                main_image_url="https://example.com/image.jpg",
                brand="Example Brand",
                size="Large",
                color="Black",
                variant_attributes={"Size": "Large", "Color": "Black"},
                bullet_points=["Point 1", "Point 2"],
                collected_at=datetime(2026, 6, 14, 12, 0, 0),
            )
        ]


def test_collect_returns_saved_snapshots(monkeypatch) -> None:
    saved_rows = [
        {
            "id": 11,
            "family_key": "abc123",
            "marketplace": "www.amazon.com",
            "source_url": "https://www.amazon.com/dp/B0TESTASIN",
            "title": "Example product",
            "rating": "4.8 out of 5 stars",
            "review_count": "128",
            "main_image_url": "https://example.com/image.jpg",
            "brand": "Example Brand",
            "variant_dimensions": ["Size", "Color"],
            "bullet_points": ["Point 1", "Point 2"],
            "selection_id": None,
            "selection_status": None,
            "variants": [
                {
                    "id": 21,
                    "asin": "B0TESTASIN",
                    "price_text": "$19.99",
                    "size": "Large",
                    "color": "Black",
                    "variant_attributes": {"Size": "Large", "Color": "Black"},
                }
            ],
        }
    ]

    monkeypatch.setattr(collection_service, "AmazonCollector", lambda: StubCollector())
    monkeypatch.setattr(
        collection_service.database,
        "save_raw_product_families",
        lambda task_id, families: saved_rows,
    )

    client = TestClient(main.app)
    response = client.post("/api/collect", json={"url": "https://www.amazon.com/dp/B0TESTASIN"})

    assert response.status_code == 200
    assert response.json() == saved_rows
