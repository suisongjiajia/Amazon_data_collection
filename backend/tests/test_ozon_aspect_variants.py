from collector.ozon.models import OzonProductInfo
from collector.ozon.parser import parse_product_aspects
from services.ozon_attribute_fill import is_variant_aspect_attr_name
from services.ozon_collection_service import _expand_variants
import json


def test_parse_product_aspects_from_web_aspects_widget():
    aspects_payload = {
        "aspects": [
            {
                "aspectName": "Цвет",
                "variants": [
                    {
                        "sku": "111",
                        "link": "https://www.ozon.ru/product/111/",
                        "active": True,
                        "data": {
                            "searchableText": "бордовый",
                            "textRs": [{"type": "text", "content": "бордовый"}],
                            "title": "Платье EAGLETEX",
                        },
                    },
                    {
                        "sku": "222",
                        "link": "https://www.ozon.ru/product/222/",
                        "data": {
                            "searchableText": "чёрный",
                            "title": "Платье EAGLETEX",
                        },
                    },
                ],
            },
            {
                "aspectName": "Размер",
                "variants": [
                    {
                        "sku": "111",
                        "active": True,
                        "data": {"searchableText": "42 RU / XS"},
                    },
                    {
                        "sku": "333",
                        "data": {"textRs": [{"content": "44 RU / S"}]},
                    },
                ],
            },
        ]
    }
    page = {"widgetStates": {"webAspects-123": json.dumps(aspects_payload)}}
    aspects = parse_product_aspects(page)
    by_sku = {item["sku"]: item for item in aspects}
    assert set(by_sku) == {"111", "222", "333"}
    assert by_sku["111"]["attributes"]["Цвет"] == "бордовый"
    assert by_sku["111"]["attributes"]["Размер"] == "42 RU / XS"
    assert by_sku["111"]["active"] is True
    assert by_sku["222"]["attributes"]["Цвет"] == "чёрный"
    assert by_sku["333"]["attributes"]["Размер"] == "44 RU / S"


def test_expand_variants_multi_sku():
    product = OzonProductInfo(
        product_id="111",
        title="Футболка",
        price_text="999 ₽",
        source_url="https://www.ozon.ru/product/111/",
        main_image_url="https://example.com/a.jpg",
        variant_attributes={"Цвет": "Чёрный"},
    )
    aspects = [
        {"sku": "111", "attributes": {"Цвет": "Чёрный"}, "active": True},
        {"sku": "222", "attributes": {"Цвет": "Белый"}, "image": "https://example.com/b.jpg"},
    ]
    variants = _expand_variants(product, aspects)
    assert len(variants) == 2
    assert variants[0]["external_id"] == "111"
    assert variants[1]["external_id"] == "222"
    assert variants[1]["variant_attributes"]["Цвет"] == "Белый"
    assert "Белый" in (variants[1]["title"] or "")


def test_expand_variants_single_keeps_one():
    product = OzonProductInfo(
        product_id="999",
        title="Стойка",
        price_text="1500 ₽",
        source_url="https://www.ozon.ru/product/999/",
        variant_attributes={},
    )
    variants = _expand_variants(product, [])
    assert len(variants) == 1
    assert variants[0]["external_id"] == "999"


def test_is_variant_aspect_attr_name():
    assert is_variant_aspect_attr_name("Цвет")
    assert is_variant_aspect_attr_name("Color")
    assert is_variant_aspect_attr_name("Размер")
    assert is_variant_aspect_attr_name("尺码")
    assert not is_variant_aspect_attr_name("Бренд")
    assert not is_variant_aspect_attr_name("Название модели")
