import json
from pathlib import Path

import pytest

from collector.ozon.collector import OzonCollector
from collector.ozon.parser import (
    extract_next_page_path,
    parse_listing_page,
    parse_product_details,
    parse_search_item,
)
from collector.ozon.url_parser import OzonUrlParser, OzonUrlType

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_search_item_ignores_non_numeric_rating_label():
    item = {
        "sku": "3333333333",
        "action": {"link": "/product/item-3333333333/"},
        "mainState": [
            {"id": "name", "textDS": {"text": "商品"}},
            {"type": "priceV2", "priceV2": {"price": [{"textStyle": "PRICE", "text": "100 ₽"}]}},
            {
                "labelListV2": {
                    "items": [
                        {"type": "text", "text": {"text": "16 和 1\u2009P"}},
                        {"type": "text", "text": {"text": "12 отзывов"}},
                    ]
                }
            },
        ],
    }
    parsed = parse_search_item(item)
    assert parsed is not None
    assert parsed["sku"] == "3333333333"
    assert parsed["price"] == 100
    assert parsed.get("rating") is None

    rated = {
        "sku": "4444444444",
        "action": {"link": "/product/item-4444444444/"},
        "mainState": [
            {"id": "name", "textDS": {"text": "商品"}},
            {"type": "priceV2", "priceV2": {"price": [{"textStyle": "PRICE", "text": "80 ₽"}]}},
            {
                "labelListV2": {
                    "items": [
                        {"type": "text", "text": {"text": "4,8"}},
                        {"type": "text", "text": {"text": "12"}},
                    ]
                }
            },
        ],
    }
    parsed_rated = parse_search_item(rated)
    assert parsed_rated is not None
    assert parsed_rated["rating"] == 4.8
    assert parsed_rated["reviews"] == 12


def test_parse_listing_page_skips_recommendation_grid():
    shop_item = {
        "sku": "1111111111",
        "action": {"link": "/product/shop-item-1111111111/"},
        "mainState": [
            {"id": "name", "textDS": {"text": "本店商品"}},
            {"type": "priceV2", "priceV2": {"price": [{"textStyle": "PRICE", "text": "100 ₽"}]}},
        ],
    }
    other_shop_item = {
        "sku": "2222222222",
        "action": {"link": "/product/other-shop-2222222222/"},
        "mainState": [
            {"id": "name", "textDS": {"text": "别的店"}},
            {"type": "priceV2", "priceV2": {"price": [{"textStyle": "PRICE", "text": "200 ₽"}]}},
        ],
    }
    page = {
        "widgetStates": {
            "tileGridDesktop-1": json.dumps({"items": [shop_item], "page": 1}),
            "tileGridDesktop-2": json.dumps(
                {
                    "header": {"title": {"text": "您可能喜欢"}},
                    "items": [other_shop_item],
                }
            ),
        }
    }
    items = parse_listing_page(page, limit=50)
    assert [item["sku"] for item in items] == ["1111111111"]


def test_extract_next_page_path_from_standalone_paginator():
    page = {
        "widgetStates": {
            "tileGridDesktop-1": json.dumps(
                {
                    "items": [
                        {
                            "sku": "1111111111",
                            "action": {"link": "/product/shop-item-1111111111/"},
                            "mainState": [
                                {"type": "priceV2", "priceV2": {"price": [{"textStyle": "PRICE", "text": "100 ₽"}]}}
                            ],
                        }
                    ]
                }
            ),
            "infiniteVirtualPaginator-1": json.dumps(
                {"nextPage": "/seller/zaocai/?page=2&sorting=score", "size": 10}
            ),
        }
    }
    assert extract_next_page_path(page) == "/seller/zaocai/?page=2&sorting=score"


def test_parse_listing_page_from_fixture():
    page = load_fixture("ozon_listing_page.json")
    items = parse_listing_page(page, limit=10)
    assert len(items) == 1
    assert items[0]["sku"] == "1234567890"


def test_url_parser_product_and_seller():
    product = OzonUrlParser().parse(
        "https://www.ozon.ru/product/otboynik-dlya-dveri-3522488453/"
    )
    assert product.type is OzonUrlType.PRODUCT
    assert product.product_id == "3522488453"

    seller = OzonUrlParser().parse("https://www.ozon.ru/seller/partszone/")
    assert seller.type is OzonUrlType.SELLER
    assert seller.seller_slug == "partszone"


def test_ozon_collector_with_mocked_http():
    page = load_fixture("ozon_listing_page.json")
    collector = OzonCollector()
    collector._prepare_session = lambda parsed=None: None  # type: ignore[method-assign]
    collector._fetch_page = lambda path: page  # type: ignore[method-assign]
    collector._sleep = lambda ms: None  # type: ignore[method-assign]

    products = collector.collect("https://www.ozon.ru/category/smartfony-15502/")
    assert len(products) >= 1
    assert products[0].product_id == "1234567890"


def test_parse_product_details_prefers_regular_price_over_card_price():
    page = {
        "widgetStates": {
            "webGallery-1": json.dumps({"sku": "4943881760", "coverImage": "https://example.com/a.jpg"}),
            "webProductHeading-1": json.dumps({"title": "Пуллер"}),
            "webPrice-1": json.dumps(
                {
                    "cardPrice": "287\u2009₽",
                    "price": "302\u2009₽",
                    "originalPrice": "1\u2009123\u2009₽",
                }
            ),
        }
    }
    details = parse_product_details(page)
    assert details["price"] == 302
    assert details["card_price"] == 287
    assert details["old_price"] == 1123


def test_parse_product_details_from_fixture():
    page = load_fixture("ozon_product_details.json")
    details = parse_product_details(page, page)
    assert details["sku"] == "1002277569"
    assert "Zekkert" in (details.get("description") or "")
    assert details["attributes"]["Тип"] == "стабилизатор"
    assert details["attributes"]["Длина, мм"] == "298"
    assert details["size"] == "298×80×60 mm"
    assert details["category_name"] == "Авто / Запчасти"
    assert details["description_category_id"] == "17028922"
    assert details["type_id"] == "971438216"


def test_apply_cookie_string():
    from collector.ozon.collector import apply_cookie_string

    class FakeCookies:
        def __init__(self) -> None:
            self.items: list[tuple[str, str, str]] = []

        def set(self, name: str, value: str, domain: str) -> None:
            self.items.append((name, value, domain))

    session = type("Session", (), {"cookies": FakeCookies()})()
    apply_cookie_string(session, "foo=bar; secure=1")
    assert ("foo", "bar", ".ozon.ru") in session.cookies.items
