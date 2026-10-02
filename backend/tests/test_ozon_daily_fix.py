from __future__ import annotations

from services.ozon_daily_fix_service import VISIBILITY_BUCKETS, _seconds_until_next_run


def test_visibility_buckets_cover_seller_tabs():
    assert "准备销售" in VISIBILITY_BUCKETS
    assert "错误" in VISIBILITY_BUCKETS
    assert "待修改" in VISIBILITY_BUCKETS
    assert "READY_TO_SUPPLY" in VISIBILITY_BUCKETS["准备销售"]
    assert "STATE_FAILED" in VISIBILITY_BUCKETS["错误"]
    assert "VALIDATION_STATE_FAIL" in VISIBILITY_BUCKETS["待修改"]


def test_seconds_until_next_run_positive(monkeypatch):
    monkeypatch.setenv("OZON_DAILY_FIX_HOUR", "3")
    monkeypatch.setenv("OZON_DAILY_FIX_MINUTE", "0")
    monkeypatch.setenv("OZON_DAILY_FIX_TZ", "Asia/Shanghai")
    assert _seconds_until_next_run() >= 5
