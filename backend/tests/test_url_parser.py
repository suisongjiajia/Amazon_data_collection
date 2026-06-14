from collector.models import UrlType
from collector.url_parser import AmazonUrlParser


def test_parse_product_url() -> None:
    result = AmazonUrlParser().parse("https://www.amazon.com/dp/B0BRKPBMVY")
    assert result.type is UrlType.PRODUCT
    assert result.asin == "B0BRKPBMVY"
    assert result.listing_url == "https://www.amazon.com/dp/B0BRKPBMVY"


def test_parse_product_url_with_locale_path() -> None:
    result = AmazonUrlParser().parse(
        "https://www.amazon.com/-/zh/dp/B0BRKPBMVY?th=1&psc=1"
    )
    assert result.type is UrlType.PRODUCT
    assert result.asin == "B0BRKPBMVY"
    assert result.locale_prefix == "/-/zh"
    assert result.listing_url == "https://www.amazon.com/-/zh/dp/B0BRKPBMVY"


def test_parse_store_url() -> None:
    result = AmazonUrlParser().parse("https://www.amazon.com/s?me=A1B2C3D4E5")
    assert result.type is UrlType.STORE
    assert result.asin is None
    assert result.seller_id == "A1B2C3D4E5"


def test_parse_category_url() -> None:
    result = AmazonUrlParser().parse("https://www.amazon.com/s?rh=n%3A172282")
    assert result.type is UrlType.CATEGORY
    assert result.asin is None
