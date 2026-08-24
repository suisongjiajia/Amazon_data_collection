from services.sourcing_service import _enrich_ozon_family_for_display, get_sourcing_detail


def test_enrich_ozon_family_for_display_extracts_details():
    family = {
        "id": 1,
        "external_id": "366274688",
        "title": "RD5 雨刮片",
        "brand": "RD5",
        "main_image_url": "https://example.com/main.jpg",
        "raw_payload": {
            "price": 769,
            "rawPayload": {
                "details": {
                    "sku": "366274688",
                    "description": "雨刮器说明",
                    "price": 769,
                    "images": ["https://example.com/1.jpg", "https://example.com/2.jpg"],
                    "attributes": {"Тип": "стабилизатор"},
                }
            },
        },
        "variants": [
            {
                "price_text": "769 ₽",
                "size": "60+40 cm",
                "variant_attributes": {"weight": "320 g"},
            }
        ],
        "variant_count": 1,
    }

    product = _enrich_ozon_family_for_display(family)
    assert product["sku"] == "366274688"
    assert product["description"] == "雨刮器说明"
    assert product["size"] == "60+40 cm"
    assert product["weight"] == "320 g"
    assert product["attributes"]["Тип"] == "стабилизатор"
    assert len(product["images"]) == 2


def test_get_sourcing_detail(monkeypatch):
    family = {
        "id": 3,
        "external_id": "100",
        "title": "测试商品",
        "variants": [],
        "variant_count": 0,
        "raw_payload": {},
    }
    candidates = [{"id": 9, "raw_product_family_id": 3, "supplier_name": "供应商A", "status": "candidate"}]

    monkeypatch.setattr("services.sourcing_service.get_ozon_product_family", lambda _id: family)
    monkeypatch.setattr("services.sourcing_service.list_supplier_candidates", lambda _id, limit=100: candidates)

    detail = get_sourcing_detail(3)
    assert detail["product"]["title"] == "测试商品"
    assert len(detail["candidates"]) == 1
