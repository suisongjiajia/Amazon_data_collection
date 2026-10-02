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


def test_both_aspect_writes_color_and_steps(monkeypatch):
    """宠物梯子类：颜色 + 阶数双轴必须同时写入。"""
    from services import ozon_attribute_fill as fill

    schema = [
        {"id": 10097, "name": "Название цвета", "is_aspect": True, "type": "String", "dictionary_id": 0},
        {"id": 10096, "name": "Цвет товара", "is_aspect": True, "type": "String", "dictionary_id": 1494},
        {"id": 9533, "name": "Размер", "is_aspect": True, "type": "String", "dictionary_id": 0},
        {"id": 9048, "name": "Название модели", "is_aspect": False, "type": "String", "dictionary_id": 0},
    ]
    monkeypatch.setattr(fill, "fetch_category_attributes", lambda *_a, **_k: schema)

    def fake_pick(**kwargs):
        q = " ".join(str(x) for x in (kwargs.get("queries") or []))
        if "син" in q.lower() or "蓝" in q:
            return {"dictionary_value_id": 61570, "value": "синий"}
        return {"dictionary_value_id": 61576, "value": "серый"}

    monkeypatch.setattr(fill, "pick_dictionary_value", fake_pick)
    base = [
        {"id": 9048, "values": [{"value": "Лестница-пандус"}]},
        {"id": 10097, "values": [{"value": "серый"}]},
        {"id": 10096, "values": [{"dictionary_value_id": 61576}]},
        {"id": 9533, "values": [{"value": "3 ступени"}]},
    ]
    blue3 = fill.apply_variant_distinguishing_attributes(
        base,
        description_category_id=1,
        type_id=2,
        variant_attributes={"颜色": "蓝色", "尺码": "3层"},
        edit_title="Лестница синяя 3 ступени",
        variant_aspect="both",
    )
    by_id = {int(item["id"]): item for item in blue3}
    assert by_id[10096]["values"][0]["dictionary_value_id"] == 61570
    assert "син" in by_id[10097]["values"][0]["value"].lower() or by_id[10097]["values"][0]["value"]
    assert by_id[9533]["values"][0]["value"] == "3 ступени"


def test_detect_and_enrich_dual_aspect():
    from services.ozon_attribute_fill import (
        detect_variant_aspect_mode,
        enrich_variant_aspect_fields,
        infer_color_label,
        listing_size_label,
        resolve_variant_aspect_pair,
    )

    assert listing_size_label("3层") == "3 ступени"
    assert listing_size_label("三层缓步楼梯（灰色）高30CM") == "3 ступени"
    assert listing_size_label("灰色三阶直角【高30CM】") == "3 ступени"
    assert listing_size_label("蓝色 · 5层") == "5 ступени"
    assert listing_size_label("чехол 3 ступени") == "чехол 3 ступени"
    assert listing_size_label("可拆洗布套（三层/不含楼梯）") == "чехол 3 ступени"
    assert listing_size_label("只是单独换洗外套（不含填充物楼梯） / 灰色三阶直角【高30CM】") == "чехол 3 ступени"
    from services.ozon_attribute_fill import resolve_variant_aspect_pair

    stair = resolve_variant_aspect_pair(
        {"规格": "25D高弹海绵/可拆洗/宠物楼梯 / 灰色三阶直角【高30CM】"},
        title="Сменный чехол серый, 3 ступени",
    )
    assert stair == ("серый", "3 ступени")
    cover = resolve_variant_aspect_pair(
        {"规格": "只是单独换洗外套（不含填充物楼梯） / 灰色三阶直角【高30CM】"},
        title="Серый, 3 ступени",
    )
    assert cover == ("серый чехол", "чехол 3 ступени")
    enriched = enrich_variant_aspect_fields(
        {
            "规格": "只是单独换洗外套（不含填充物楼梯） / 灰色三阶直角【高30CM】",
            "Название цвета": "серый чехол",
            "Размер": "чехол 3 ступени",
            "颜色": "серый чехол",
            "尺码": "чехол 3 ступени",
        }
    )
    assert enriched.get("Размер") == "чехол 3 ступени"
    assert infer_color_label("深灰色三层楼梯") == "тёмно-серый"
    assert infer_color_label("灰色三层楼梯") == "серый"
    assert infer_color_label("тёмно-серый") == "тёмно-серый"
    assert infer_color_label("黄绿四层") == "жёлто-зелёный"
    enriched = enrich_variant_aspect_fields({"区分项": "灰色 · 4层"})
    assert "灰" in enriched.get("颜色", "") or enriched.get("颜色")
    assert enriched.get("Размер") == "4 ступени"
    variants = [
        {"variant_attributes": {"颜色": "蓝色", "尺码": "3层"}},
        {"variant_attributes": {"颜色": "灰色", "尺码": "5层"}},
        {"variant_attributes": {"颜色": "米色", "尺码": "4层"}},
    ]
    assert detect_variant_aspect_mode(variants) == "both"
    assert detect_variant_aspect_mode(
        [
            {"variant_attributes": {"颜色": "蓝色"}},
            {"variant_attributes": {"颜色": "灰色"}},
        ]
    ) == "color"


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
    from services.ozon_attribute_fill import listing_color_label, listing_size_label, parse_packed_color_size

    assert listing_color_label("带三个孔和鹿角的隧道", "Тоннель-лежак 85 см, серый") == "серый"
    assert listing_color_label("三孔绿色蘑菇隧道", "Тоннель-лежак, зеленый") == "зеленый"
    assert listing_color_label("серый", "зеленый") == "серый"
    assert listing_color_label("清新绿-耐磨 · XL75*60cm（建议30斤内）") == "зеленый"
    assert listing_size_label("清新绿 · L 60*50cm（建议15斤内）") == "L 60x50"
    assert listing_size_label("L 60*50cm（建议15斤内犬猫）") == "L 60x50"
    assert parse_packed_color_size("灰色S(40*50)CM") == ("灰色", "S 40x50")
    assert parse_packed_color_size("咖色XL(66*90)CM") == ("咖色", "XL 66x90")
    assert listing_color_label("灰色S(40*50)CM") == "серый"
    assert listing_size_label("灰色S(40*50)CM") == "S 40x50"
    assert listing_color_label("咖色M(48*60)CM") == "коричневый"
    assert listing_size_label("咖色M(48*60)CM") == "M 48x60"


def test_size_label_to_mm_and_packed_specs():
    from services.ozon_attribute_fill import listing_aspect_size_mm, size_label_to_mm

    assert size_label_to_mm("S 40x50") == "400*500*80"
    assert size_label_to_mm("XL 66x90") == "660*900*80"
    assert listing_aspect_size_mm("灰色S(40*50)CM") == "400*500*80"
    assert listing_aspect_size_mm("咖色XL(66*90)CM") == "660*900*80"


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
