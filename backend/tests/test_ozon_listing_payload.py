from services.ozon_listing_payload import (
    build_import_items,
    build_stock_items,
    package_metrics_issues,
    preview_listing,
)
from integrations.ozon_seller.client import OzonSellerError
import pytest


@pytest.fixture(autouse=True)
def _mock_attribute_fill(monkeypatch):
    def fake_build(*, description_category_id, type_id, edit_attributes, **_kwargs):
        return (
            [
                {"id": 85, "values": [{"dictionary_value_id": 126745801}]},
                {"id": 9048, "values": [{"value": "SharedModel"}]},
            ],
            [],
        )

    def fake_apply(base_attributes, *, variant_attributes=None, **_kwargs):
        result = [dict(item) for item in base_attributes]
        overrides = variant_attributes or {}
        color = overrides.get("Цвет") or overrides.get("Color") or overrides.get("颜色")
        if color:
            result.append({"id": 10096, "values": [{"value": str(color)}]})
        return result

    monkeypatch.setattr(
        "services.ozon_attribute_fill.build_ozon_attribute_values",
        fake_build,
    )
    monkeypatch.setattr(
        "services.ozon_attribute_fill.apply_variant_distinguishing_attributes",
        fake_apply,
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
        "images": [f"https://example.com/{i}.jpg" for i in range(1, 6)],
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


def test_build_import_items_includes_category_type_and_no_brand(monkeypatch):
    monkeypatch.setenv("OZON_FORCE_PACKAGE_METRICS", "true")
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
    assert items[0]["depth"] == 100
    assert items[0]["width"] == 100
    assert items[0]["height"] == 100
    assert items[0]["weight"] == 200


def test_package_metrics_rejects_unrealistic_light_weight(monkeypatch):
    monkeypatch.setenv("OZON_FORCE_PACKAGE_METRICS", "false")
    issues = package_metrics_issues(
        {
            "length_mm": "550",
            "width_mm": "402",
            "height_mm": "330",
            "weight_g": "20",
        },
        variants=[{"sku": "OZON-758101316", "price": 58.99, "quantity": 1}],
    )
    assert any(item.get("code") == "UNREALISTIC_PACKAGE_METRICS" for item in issues)


def test_build_import_items_requires_category_and_type():
    edit = {
        "title": "x",
        "attributes": {},
        "variants": [{"sku": "OZON-1", "price": 100, "quantity": 1}],
        "images": [],
    }
    with pytest.raises(OzonSellerError, match="description_category_id"):
        build_import_items(edit)


def test_build_stock_items_for_rfbs(monkeypatch):
    monkeypatch.setenv("OZON_DEFAULT_STOCK_QTY", "99")
    edit = {
        "variants": [
            {"sku": "OZON-1", "quantity": 10},
            {"sku": "OZON-2", "quantity": 0},
        ]
    }
    stocks = build_stock_items(edit, warehouse_id=123)
    assert stocks == [
        {"offer_id": "OZON-1", "stock": 10, "warehouse_id": 123},
        {"offer_id": "OZON-2", "stock": 99, "warehouse_id": 123},
    ]


def test_build_import_items_multi_variant_shares_model_differs_color():
    edit = {
        "title": "Футболка",
        "description": "Описание",
        "images": ["https://example.com/1.jpg"],
        "attributes": {
            "description_category_id": "17028922",
            "type_id": "971438216",
            "Длина, мм": "300",
            "Ширина, мм": "200",
            "Высота, мм": "20",
            "Вес, г": "180",
        },
        "variants": [
            {
                "sku": "OZON-111",
                "title": "Футболка (Чёрный)",
                "price": 999,
                "quantity": 5,
                "variant_attributes": {"Цвет": "Чёрный"},
            },
            {
                "sku": "OZON-222",
                "title": "Футболка (Белый)",
                "price": 1099,
                "quantity": 3,
                "variant_attributes": {"Цвет": "Белый"},
            },
        ],
    }
    items = build_import_items(edit)
    assert len(items) == 2
    assert items[0]["offer_id"] == "OZON-111"
    assert items[1]["offer_id"] == "OZON-222"
    # 合卡：型号名一致
    model0 = next(a for a in items[0]["attributes"] if a["id"] == 9048)
    model1 = next(a for a in items[1]["attributes"] if a["id"] == 9048)
    assert model0 == model1
    # 区分：颜色不同
    color0 = next(a for a in items[0]["attributes"] if a["id"] == 10096)
    color1 = next(a for a in items[1]["attributes"] if a["id"] == 10096)
    assert color0["values"][0]["value"] == "Чёрный"
    assert color1["values"][0]["value"] == "Белый"


def test_build_import_items_per_variant_package_dimensions(monkeypatch):
    from services.ozon_listing_payload import parse_size_triplet_mm

    monkeypatch.setenv("OZON_FORCE_PACKAGE_METRICS", "false")
    assert parse_size_triplet_mm("360*360") == (360, 360, 360)
    assert parse_size_triplet_mm("330x330x330") == (330, 330, 330)
    assert parse_size_triplet_mm("420×420") == (420, 420, 420)

    edit = {
        "title": "Домик",
        "description": "desc",
        "images": ["https://example.com/1.jpg"],
        "attributes": {
            "description_category_id": "17028674",
            "type_id": "95199",
            "Длина, мм": "360",
            "Ширина, мм": "360",
            "Высота, мм": "360",
            "Вес, г": "500",
        },
        "variants": [
            {
                "sku": "OZON-A",
                "price": 54,
                "quantity": 99,
                "variant_attributes": {"Размеры, мм": "360*360"},
            },
            {
                "sku": "OZON-B",
                "price": 54,
                "quantity": 99,
                "variant_attributes": {"Размеры, мм": "330x330x330"},
            },
            {
                "sku": "OZON-C",
                "price": 54,
                "quantity": 99,
                "variant_attributes": {"Размеры, мм": "420*420"},
            },
        ],
    }
    items = build_import_items(edit)
    assert [(i["offer_id"], i["depth"], i["width"], i["height"], i["weight"]) for i in items] == [
        ("OZON-A", 360, 360, 360, 500),
        ("OZON-B", 330, 330, 330, 500),
        ("OZON-C", 420, 420, 420, 500),
    ]
    assert items[0]["old_price"] == "70.2"
    assert items[0]["price"] == "54"


def test_forced_package_metrics_override_all_variants(monkeypatch):
    monkeypatch.setenv("OZON_FORCE_PACKAGE_METRICS", "true")
    monkeypatch.setenv("OZON_FIXED_DEPTH_MM", "100")
    monkeypatch.setenv("OZON_FIXED_WIDTH_MM", "100")
    monkeypatch.setenv("OZON_FIXED_HEIGHT_MM", "100")
    monkeypatch.setenv("OZON_FIXED_WEIGHT_G", "200")
    edit = {
        "title": "x",
        "description": "d",
        "images": ["https://example.com/1.jpg"],
        "attributes": {
            "description_category_id": "1",
            "type_id": "2",
            "Длина, мм": "999",
            "Ширина, мм": "888",
            "Высота, мм": "777",
            "Вес, г": "10",
        },
        "variants": [
            {"sku": "A", "price": 10, "quantity": 1, "variant_attributes": {"Размеры, мм": "500*500"}},
            {"sku": "B", "price": 10, "quantity": 1},
        ],
    }
    items = build_import_items(edit)
    assert all(i["depth"] == 100 and i["width"] == 100 and i["height"] == 100 and i["weight"] == 200 for i in items)


def test_net_product_size_is_not_used_as_package(monkeypatch):
    monkeypatch.setenv("OZON_FORCE_PACKAGE_METRICS", "false")
    from services.ozon_listing_payload import read_net_product_mm, read_package_metrics

    attrs = {
        "depth_mm": "100",
        "width_mm": "110",
        "height_mm": "120",
        "weight_g": "200",
        "net_depth_mm": "300",
        "net_width_mm": "40",
        "net_height_mm": "20",
        "Размеры товара, мм": "300*40*20",
    }
    assert read_package_metrics(attrs)[:3] == (100, 110, 120)
    assert read_net_product_mm(attrs) == (300, 40, 20)
    assert read_package_metrics(
        {
            "net_depth_mm": "300",
            "net_width_mm": "40",
            "net_height_mm": "20",
            "Размеры товара, мм": "300*40*20",
        }
    )[0] is None


def test_each_variant_listing_uses_own_images_only():
    from services.ozon_listing_payload import _prefer_reachable_listing_images, build_import_items

    oss = [f"https://bucket.aliyuncs.com/{i}.jpg" for i in range(1, 7)]
    ozon = "https://cdn1.ozone.ru/s3/multimedia-1/wc140/123.jpg"
    result = _prefer_reachable_listing_images([*oss, ozon])
    assert result[0] == oss[0]
    assert "wc1200" in result[-1]

    edit = {
        "title": "嘴套",
        "description": "d",
        "images": oss,
        "attributes": {
            "description_category_id": "1",
            "type_id": "2",
            "Длина, мм": "100",
            "Ширина, мм": "100",
            "Высота, мм": "100",
            "Вес, г": "200",
        },
        "variants": [
            {
                "sku": "OZON-S",
                "price": 10,
                "quantity": 99,
                "image_url": "https://cdn1.ozone.ru/s3/multimedia-1/wc140/s-main.jpg",
                "variant_attributes": {
                    "Размер": "S",
                    "images": [
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/s-main.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/s-2.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/s-3.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/s-4.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/s-5.jpg",
                    ],
                },
            },
            {
                "sku": "OZON-L",
                "price": 12,
                "quantity": 99,
                "image_url": "https://cdn1.ozone.ru/s3/multimedia-1/wc140/l-main.jpg",
                "variant_attributes": {
                    "Размер": "L",
                    "images": [
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/l-main.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/l-2.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/l-3.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/l-4.jpg",
                        "https://cdn1.ozone.ru/s3/multimedia-1/wc140/l-5.jpg",
                    ],
                },
            },
        ],
    }
    items = build_import_items(edit)
    assert len(items) == 2
    assert "s-main" in items[0]["images"][0]
    assert "l-main" in items[1]["images"][0]
    assert all("s-" in url or "wc1200" in url for url in items[0]["images"])
    assert all("l-" in url or "wc1200" in url for url in items[1]["images"])
    assert oss[0] not in items[0]["images"]
    assert oss[0] not in items[1]["images"]
    assert items[0]["images"] != items[1]["images"]


def test_product_centimeters_are_not_used_as_package_mm(monkeypatch):
    monkeypatch.setenv("OZON_FORCE_PACKAGE_METRICS", "true")
    edit = {
        "title": "Тоннель 85 см",
        "description": "d",
        "images": ["https://example.com/1.jpg"],
        "attributes": {
            "description_category_id": "1",
            "type_id": "2",
            "package_manual": "1",
            "depth_mm": "400",
            "width_mm": "500",
            "height_mm": "500",
            "weight_g": "200",
            "Длина рукава, см": "85",
        },
        "variants": [
            {
                "sku": "OZON-4246785373",
                "price": 58,
                "quantity": 99,
                "title": "Тоннель-лежак 85 см, серый с тремя отверстиями и рожками",
                "variant_attributes": {"袖长，厘米": "85"},
            }
        ],
    }
    items = build_import_items(edit)
    # 400×500×500 mm 配 200g 过轻，回落到统一包裹，而不是标题里的 85 厘米
    assert (items[0]["depth"], items[0]["width"], items[0]["height"], items[0]["weight"]) == (
        100,
        100,
        100,
        200,
    )
