from config import get_ozon_cookie, get_ozon_seller_ui_cookie


def test_cookie_fallback(monkeypatch):
    monkeypatch.setenv("OZON_COOKIE", "a=1")
    monkeypatch.delenv("OZON_SELLER_COOKIE", raising=False)
    assert get_ozon_cookie() == "a=1"
    assert get_ozon_seller_ui_cookie() == "a=1"


def test_seller_cookie_override(monkeypatch):
    monkeypatch.setenv("OZON_COOKIE", "a=1")
    monkeypatch.setenv("OZON_SELLER_COOKIE", "b=2")
    assert get_ozon_cookie() == "a=1"
    assert get_ozon_seller_ui_cookie() == "b=2"


def test_cookie_uses_seller_when_primary_empty(monkeypatch):
    monkeypatch.setenv("OZON_COOKIE", "")
    monkeypatch.setenv("OZON_SELLER_COOKIE", "legacy=1")
    assert get_ozon_cookie() == "legacy=1"
