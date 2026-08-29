import json
from pathlib import Path

import pytest

from collector.ozon.collector import OzonCollector
from collector.ozon.parser import parse_listing_page, parse_product_details
from collector.ozon.url_parser import OzonUrlParser, OzonUrlType

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


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
