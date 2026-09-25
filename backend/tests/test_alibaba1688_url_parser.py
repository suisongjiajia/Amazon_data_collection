from collector.alibaba1688.url_parser import (
    Alibaba1688UrlParser,
    Alibaba1688UrlType,
    is_1688_shop_url,
)


def test_parse_offer_url():
    parsed = Alibaba1688UrlParser().parse("https://detail.1688.com/offer/724512345678.html?spm=a")
    assert parsed.type is Alibaba1688UrlType.OFFER
    assert parsed.offer_id == "724512345678"
    assert parsed.source_url.endswith("/724512345678.html")


def test_parse_shop_subdomain():
    parsed = Alibaba1688UrlParser().parse("https://shop1234567890.1688.com/")
    assert parsed.type is Alibaba1688UrlType.SHOP
    assert "shop1234567890.1688.com" in parsed.source_url
    assert is_1688_shop_url("https://shop1234567890.1688.com/page/offerlist.htm")


def test_parse_offerlist_path():
    parsed = Alibaba1688UrlParser().parse("https://winport.1688.com/page/offerlist.htm?memberId=b2b-xxx")
    assert parsed.type is Alibaba1688UrlType.SHOP


def test_reject_empty():
    try:
        Alibaba1688UrlParser().parse("")
        assert False
    except ValueError:
        pass
