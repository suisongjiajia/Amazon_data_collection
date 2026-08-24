from services.ozon_listing_payload import build_import_items


def test_build_import_items_from_edit():
    edit = {
        "title": "Стойки стабилизатора",
        "description": "Описание",
        "bullet_points": ["2 шт"],
        "images": ["https://example.com/1.jpg"],
        "attributes": {"Длина, мм": "298", "Ширина, мм": "80", "Высота, мм": "60", "Вес, г": "500"},
        "variants": [{"sku": "OZON-100", "title": "Стойки", "price": 1599, "quantity": 10}],
    }
    items = build_import_items(edit)
    assert len(items) == 1
    assert items[0]["offer_id"] == "OZON-100"
    assert items[0]["price"] == "1599"
    assert items[0]["depth"] == 298
    assert items[0]["weight"] == 500
