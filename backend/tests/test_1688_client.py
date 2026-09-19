from collector.alibaba1688.cdp_cookies import _cookie_header, is_token_error
from collector.alibaba1688.client import Alibaba1688Client


def test_normalize_ozonstatic_cn_image_url_to_wc500():
    original = "https://ir-20.ozonstatic.cn/s3/multimedia-1-v/8849420995.jpg"
    expected = "https://ir-20.ozonstatic.cn/s3/multimedia-1-v/wc500/8849420995.jpg"
    assert Alibaba1688Client._normalize_image_url(original) == expected


def test_normalize_ozone_ru_image_url_to_wc500():
    original = "https://ir.ozone.ru/s3/multimedia-1-o/8877542640.jpg"
    expected = "https://ir.ozone.ru/s3/multimedia-1-o/wc500/8877542640.jpg"
    assert Alibaba1688Client._normalize_image_url(original) == expected


def test_normalize_keeps_existing_wc500_url():
    url = "https://ir-20.ozonstatic.cn/s3/multimedia-1-z/wc500/8013230639.jpg"
    assert Alibaba1688Client._normalize_image_url(url) == url


def test_upsert_cookie_pair():
    header = "a=1; _m_h5_tk=old_1; b=2"
    updated = Alibaba1688Client._upsert_cookie_pair(header, "_m_h5_tk", "new_2")
    assert "_m_h5_tk=new_2" in updated
    assert "a=1" in updated
    assert "b=2" in updated


def test_token_error_detection():
    assert is_token_error("FAIL_SYS_TOKEN_EXOIRED::token")
    assert is_token_error("RGV587_ERROR::sm")
    assert not is_token_error("SUCCESS::调用成功")


def test_cookie_header_filters_domains():
    cookies = [
        {"name": "_m_h5_tk", "value": "abc_1", "domain": ".1688.com"},
        {"name": "other", "value": "x", "domain": ".example.com"},
        {"name": "cookie2", "value": "y", "domain": ".taobao.com"},
    ]
    header = _cookie_header(cookies)
    assert "_m_h5_tk=abc_1" in header
    assert "cookie2=y" in header
    assert "other=" not in header
