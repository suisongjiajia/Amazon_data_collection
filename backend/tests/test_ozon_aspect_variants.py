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


def test_merge_aspect_variants_completes_multi_aspect_matrix():
    from collector.ozon.parser import merge_aspect_variants

    page_a = [
        {"sku": "3640558088", "attributes": {"尺寸，毫米": "450х260х280", "Цвет": "白绿色"}, "active": True, "price": 1324},
        {"sku": "2825291464", "attributes": {"尺寸，毫米": "450x260x280"}, "price": 1329},
        {"sku": "3640452590", "attributes": {"Цвет": "黑白"}},
        {"sku": "3640520166", "attributes": {"Цвет": "黄白色"}},
    ]
    page_b = [
        {"sku": "2825291464", "attributes": {"尺寸，毫米": "450x260x280", "Цвет": "白绿色"}, "active": True, "price": 1329},
        {"sku": "2824211131", "attributes": {"Цвет": "黑白"}},
        {"sku": "2825235649", "attributes": {"Цвет": "黄白色"}},
        {"sku": "3640558088", "attributes": {"尺寸，毫米": "450х260х280"}},
    ]
    page_c = [
        {"sku": "3640452590", "attributes": {"尺寸，毫米": "450х260х280", "Цвет": "黑白"}, "active": True},
        {"sku": "2824211131", "attributes": {"尺寸，毫米": "450x260x280"}},
    ]
    merged = merge_aspect_variants(page_a, page_b, page_c)
    by_sku = {item["sku"]: item for item in merged}
    assert set(by_sku) == {
        "3640558088",
        "2825291464",
        "3640452590",
        "3640520166",
        "2824211131",
        "2825235649",
    }
    assert by_sku["3640558088"]["attributes"]["Цвет"] == "白绿色"
    assert by_sku["3640558088"]["attributes"]["尺寸，毫米"] == "450х260х280"
    assert by_sku["2824211131"]["attributes"]["Цвет"] == "黑白"
    assert by_sku["2824211131"]["attributes"]["尺寸，毫米"] == "450x260x280"


def test_expand_variants_keeps_multiple_aspect_keys():
    product = OzonProductInfo(
        product_id="3640558088",
        title="Cat&Go",
        price_text="1324 ₽",
        source_url="https://www.ozon.ru/product/3640558088/",
        main_image_url="https://example.com/a.jpg",
        variant_attributes={"类型": "宠物便携箱", "Цвет": "白绿色"},
    )
    aspects = [
        {
            "sku": "3640558088",
            "attributes": {"尺寸，毫米": "450х260х280", "Цвет": "白绿色"},
            "active": True,
            "price": 1324,
        },
        {
            "sku": "2825291464",
            "attributes": {"尺寸，毫米": "450x260x280", "Цвет": "白绿色"},
            "price": 1329,
            "image": "https://example.com/b.jpg",
        },
        {
            "sku": "3640452590",
            "attributes": {"尺寸，毫米": "450х260х280", "Цвет": "黑白"},
            "price": 1415,
        },
    ]
    variants = _expand_variants(product, aspects)
    assert len(variants) == 3
    assert variants[0]["variant_attributes"] == {"尺寸，毫米": "450х260х280", "Цвет": "白绿色"}
    assert "类型" not in variants[0]["variant_attributes"]
    assert "黑白" in (variants[2]["title"] or "")
    assert variants[1]["main_image_url"] == "https://example.com/b.jpg"


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
    assert variants[0]["price_text"] == "999 ₽"
    assert variants[1]["price_text"] is None


def test_expand_variants_root_keeps_detail_price_and_comes_first():
    product = OzonProductInfo(
        product_id="4943881760",
        title="Пуллер",
        price_text="302 ₽",
        source_url="https://www.ozon.ru/product/4943881760/",
    )
    aspects = [
        {"sku": "111", "attributes": {"Цвет": "белый"}, "price": 255},
        {"sku": "4943881760", "attributes": {"Цвет": "желтый"}, "price": 255, "active": True},
    ]
    variants = _expand_variants(product, aspects)
    assert variants[0]["external_id"] == "4943881760"
    assert variants[0]["price_text"] == "302 ₽"
    assert variants[1]["price_text"] == "255 ₽"


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
    assert is_variant_aspect_attr_name("Длина рукава, см")
    assert is_variant_aspect_attr_name("袖长，厘米")
    assert not is_variant_aspect_attr_name("Бренд")
    assert not is_variant_aspect_attr_name("Название модели")
    assert not is_variant_aspect_attr_name("Размер упаковки (Длина х Ширина х Высота), см")


def test_size_aspect_writes_distinct_sleeve_length(monkeypatch):
    from services import ozon_attribute_fill as fill

    schema = [
        {"id": 10097, "name": "Название цвета", "is_aspect": True, "type": "String", "dictionary_id": 0},
        {"id": 10096, "name": "Цвет товара", "is_aspect": True, "type": "String", "dictionary_id": 1494},
        {"id": 12606, "name": "Длина рукава, см", "is_aspect": True, "type": "Integer", "dictionary_id": 0},
        {"id": 9048, "name": "Название модели", "is_aspect": False, "type": "String", "dictionary_id": 0},
    ]
    monkeypatch.setattr(fill, "fetch_category_attributes", lambda *_a, **_k: schema)
    monkeypatch.setattr(
        fill,
        "pick_dictionary_value",
        lambda **_kwargs: {"dictionary_value_id": 61576, "value": "серый"},
    )
    base = [
        {"id": 9048, "values": [{"value": "Лежанка-туннель 3 в 1"}]},
        {"id": 10097, "values": [{"value": "Серый"}]},
        {"id": 10096, "values": [{"dictionary_value_id": 61576}]},
        {"id": 12606, "values": [{"value": "75"}]},
    ]
    short = fill.apply_variant_distinguishing_attributes(
        base,
        description_category_id=1,
        type_id=2,
        variant_attributes={"Размер": "75 см", "袖长，厘米": "75"},
        edit_title="Серый туннель, 75 см",
        variant_aspect="size",
    )
    long = fill.apply_variant_distinguishing_attributes(
        base,
        description_category_id=1,
        type_id=2,
        variant_attributes={"Размер": "85 см", "袖长，厘米": "85"},
        edit_title="Серый туннель, 85 см",
        variant_aspect="size",
    )
    short_by_id = {int(item["id"]): item for item in short}
    long_by_id = {int(item["id"]): item for item in long}
    assert 10097 not in short_by_id and 10096 not in short_by_id
    assert 10097 not in long_by_id and 10096 not in long_by_id
    assert short_by_id[12606]["values"][0]["value"] == "75"
    assert long_by_id[12606]["values"][0]["value"] == "85"
    assert short_by_id[9048]["values"][0]["value"] == long_by_id[9048]["values"][0]["value"]


def test_drop_variants_that_are_other_shop_products():
    from services.ozon_collection_service import drop_variants_listed_as_other_products

    families = drop_variants_listed_as_other_products(
        [
            {
                "external_id": "4246785373",
                "variants": [
                    {"external_id": "4246785373"},
                    {"external_id": "4246785632"},
                    {"external_id": "999"},
                ],
            },
            {
                "external_id": "4246785632",
                "variants": [
                    {"external_id": "4246785632"},
                    {"external_id": "4246785373"},
                ],
            },
        ]
    )
    assert [item["external_id"] for item in families[0]["variants"]] == ["4246785373", "999"]
    assert [item["external_id"] for item in families[1]["variants"]] == ["4246785632"]


def test_listing_color_drops_chinese_and_uses_russian_title():
    from services.ozon_attribute_fill import listing_color_label

    assert listing_color_label("带三个孔和鹿角的隧道", "Тоннель-лежак 85 см, серый") == "серый"
    assert listing_color_label("三孔绿色蘑菇隧道", "Тоннель-лежак, зеленый") == "зеленый"
    assert listing_color_label("серый", "зеленый") == "серый"


def test_same_gray_tunnels_get_distinct_color_names():
    from services.ozon_attribute_fill import disambiguate_variant_colors

    labels = disambiguate_variant_colors(
        [
            (
                "OZON-4246785373",
                "серый",
                "Тоннель-лежак 85 см, серый с тремя отверстиями и рожками",
            ),
            (
                "OZON-4246785076",
                "серый",
                "Тоннель-лежак 85 см, серый с тремя отверстиями",
            ),
        ]
    )
    assert labels["OZON-4246785076"] == "серый"
    assert labels["OZON-4246785373"] == "серый с рожками"
    assert labels["OZON-4246785373"] != labels["OZON-4246785076"]
