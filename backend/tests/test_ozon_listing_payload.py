from services.ozon_listing_payload import build_import_items, build_stock_items, preview_listing
from integrations.ozon_seller.client import OzonSellerError
import pytest


@pytest.fixture(autouse=True)
def _mock_attribute_fill(monkeypatch):
    def fake_build(*, description_category_id, type_id, edit_attributes, **_kwargs):
        return (
            [{"id": 85, "values": [{"dictionary_value_id": 126745801}]}],
            [],
        )

    monkeypatch.setattr(
        "services.ozon_attribute_fill.build_ozon_attribute_values",
        fake_build,
    )


def test_preview_listing_reports_missing_type_id():
    edit = {
        "title": "x",
        "description": "desc",
        "images": ["https://example.com/1.jpg"],
        "attributes": {"description_category_id": "17028922"},
        "variants": [{"sku": "OZON-1", "price": 100, "quantity": 1}],
    }
    preview = preview_listing(edit)
    assert preview["ok"] is False
    assert any(item["code"] == "MISSING_TYPE_ID" for item in preview["issues"])


def test_preview_listing_ok_when_complete(monkeypatch):
    monkeypatch.setenv("OZON_WAREHOUSE_ID", "123")
    edit = {
        "title": "Стойки",
        "description": "Описание",
        "bullet_points": ["2 шт"],
        "images": ["https://example.com/1.jpg"],
        "attributes": {
            "description_category_id": "17028922",
            "type_id": "971438216",
            "Длина, мм": "298",
            "Ширина, мм": "80",
            "Высота, мм": "60",
            "Вес, г": "500",
        },
        "variants": [{"sku": "OZON-100", "title": "Стойки", "price": 1599, "quantity": 10}],
    }
    preview = preview_listing(edit)
    assert preview["ok"] is True
    assert preview["payload_items"]
    assert preview["stock_items"]


def test_build_import_items_includes_category_type_and_no_brand():
    edit = {
        "title": "Стойки стабилизатора",
        "description": "Описание",
        "bullet_points": ["2 шт"],
        "images": ["https://example.com/1.jpg"],
        "attributes": {
            "description_category_id": "17028922",
            "type_id": "971438216",
            "Длина, мм": "298",
            "Ширина, мм": "80",
            "Высота, мм": "60",
            "Вес, г": "500",
        },
        "variants": [{"sku": "OZON-100", "title": "Стойки", "price": 1599, "quantity": 10}],
    }
    items = build_import_items(edit)
    assert len(items) == 1
    assert items[0]["offer_id"] == "OZON-100"
    assert items[0]["description_category_id"] == 17028922
    assert items[0]["type_id"] == 971438216
    assert items[0]["attributes"][0]["id"] == 85
    assert items[0]["depth"] == 298
    assert items[0]["weight"] == 500


def test_build_import_items_requires_category_and_type():
    edit = {
        "title": "x",
        "attributes": {},
        "variants": [{"sku": "OZON-1", "price": 100, "quantity": 1}],
        "images": [],
    }
    with pytest.raises(OzonSellerError, match="description_category_id"):
        build_import_items(edit)


def test_build_stock_items_for_rfbs():
    edit = {
        "variants": [
            {"sku": "OZON-1", "quantity": 10},
            {"sku": "OZON-2", "quantity": 0},
        ]
    }
    stocks = build_stock_items(edit, warehouse_id=123)
    assert stocks == [
        {"offer_id": "OZON-1", "stock": 10, "warehouse_id": 123},
        {"offer_id": "OZON-2", "stock": 0, "warehouse_id": 123},
    ]
