from collector.alibaba1688.client import Alibaba1688Client


def test_normalize_ozon_image_url_to_wc500():
    original = "https://ir-20.ozonstatic.cn/s3/multimedia-1-v/8849420995.jpg"
    expected = "https://ir-20.ozonstatic.cn/s3/multimedia-1-v/wc500/8849420995.jpg"
    assert Alibaba1688Client._normalize_image_url(original) == expected


def test_normalize_keeps_existing_wc500_url():
    url = "https://ir-20.ozonstatic.cn/s3/multimedia-1-z/wc500/8013230639.jpg"
    assert Alibaba1688Client._normalize_image_url(url) == url
