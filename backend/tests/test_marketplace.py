from collector.marketplace import build_marketplace_context
from collector.marketplace import extract_locale_prefix


def test_extract_locale_prefix() -> None:
    assert extract_locale_prefix("/-/zh/dp/B0BRKPBMVY") == "/-/zh"
    assert extract_locale_prefix("/dp/B0BRKPBMVY") == ""


def test_build_marketplace_context_with_locale() -> None:
    ctx = build_marketplace_context("www.amazon.com", "/-/zh")
    assert ctx.locale_prefix == "/-/zh"
    assert "zh-CN" in ctx.accept_language
    assert ctx.build_product_url("B0BRKPBMVY") == "https://www.amazon.com/-/zh/dp/B0BRKPBMVY"
    assert ctx.cookie_items()["i18n-prefs"] == "USD"


def test_build_marketplace_context_default_site() -> None:
    ctx = build_marketplace_context("www.amazon.co.uk", "")
    assert ctx.currency == "GBP"
    assert "en-GB" in ctx.accept_language
