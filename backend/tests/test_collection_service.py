from datetime import datetime

import pytest

from collector.models import ProductInfo
from services import collection_service


class StubCollector:
    def __init__(self, products: list[ProductInfo] | None = None, error: Exception | None = None) -> None:
        self._products = products or []
        self._error = error

    def collect(self, url: str) -> list[ProductInfo]:
        if self._error is not None:
            raise self._error
        return self._products


def test_collect_products_saves_and_returns_snapshots(monkeypatch) -> None:
    products = [
        ProductInfo(
            asin="B0TESTASIN",
            source_url="https://www.amazon.com/dp/B0TESTASIN",
            title="Example product",
            collected_at=datetime(2026, 6, 14, 12, 0, 0),
        )
    ]
    saved_rows = [{"id": 1, "family_key": "abc123", "variants": [{"asin": "B0TESTASIN"}]}]

    monkeypatch.setattr(collection_service, "AmazonCollector", lambda: StubCollector(products=products))
    monkeypatch.setattr(
        collection_service.database,
        "save_raw_product_families",
        lambda task_id, items: saved_rows,
    )

    result = collection_service.collect_products("https://www.amazon.com/dp/B0TESTASIN")

    assert result == saved_rows


def test_build_product_families_groups_variants() -> None:
    products = [
        ProductInfo(
            asin="B0TEST0001",
            source_url="https://www.amazon.com/dp/B0TEST0001",
            title="Example product",
            brand="Demo",
            color="Black",
            size="S",
            family_variant_asins=["B0TEST0001", "B0TEST0002"],
            variant_attributes={"Color": "Black", "Size": "S"},
            collected_at=datetime(2026, 6, 14, 12, 0, 0),
        ),
        ProductInfo(
            asin="B0TEST0002",
            source_url="https://www.amazon.com/dp/B0TEST0002",
            title="Example product",
            brand="Demo",
            color="Black",
            size="M",
            family_variant_asins=["B0TEST0001", "B0TEST0002"],
            variant_attributes={"Color": "Black", "Size": "M"},
            collected_at=datetime(2026, 6, 14, 12, 1, 0),
        ),
    ]

    families = collection_service.build_product_families(products)

    assert len(families) == 1
    assert families[0]["variant_dimensions"] == ["Color", "Size"]
    assert len(families[0]["variants"]) == 2


def test_run_collection_task_marks_failure_and_reraises(monkeypatch) -> None:
    finished_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        collection_service.database,
        "create_collection_task",
        lambda source_url: {"id": 9, "source_url": source_url},
    )
    monkeypatch.setattr(
        collection_service,
        "AmazonCollector",
        lambda: StubCollector(error=RuntimeError("network failed")),
    )

    def fake_finish_collection_task(task_id: int, **kwargs):
        finished_calls.append({"task_id": task_id, **kwargs})
        return {"id": task_id, **kwargs}

    monkeypatch.setattr(
        collection_service.database,
        "finish_collection_task",
        fake_finish_collection_task,
    )

    with pytest.raises(RuntimeError, match="network failed"):
        collection_service.run_collection_task("https://www.amazon.com/dp/B0TESTASIN")

    assert finished_calls == [
        {
            "task_id": 9,
            "status": "failed",
            "total_count": 0,
            "success_count": 0,
            "fail_count": 1,
            "error_message": "network failed",
        }
    ]
