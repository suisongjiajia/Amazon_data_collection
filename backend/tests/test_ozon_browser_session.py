from collector.ozon.browser_session import _looks_like_antibot, ozon_browser_enabled


def test_antibot_incident_without_widgets():
    assert _looks_like_antibot({"incidentId": "x"}, status=200) is True
    assert _looks_like_antibot({"widgetStates": {"a": "{}"}, "incidentId": "x"}) is False


def test_antibot_http_status():
    assert _looks_like_antibot(None, status=403) is True
    assert _looks_like_antibot({"widgetStates": {"a": "{}"}}, status=200) is False


def test_browser_enabled_default(monkeypatch):
    monkeypatch.delenv("OZON_BROWSER_ENABLED", raising=False)
    assert ozon_browser_enabled() is True
    monkeypatch.setenv("OZON_BROWSER_ENABLED", "false")
    assert ozon_browser_enabled() is False
