from collector.alibaba1688.parser import parse_supplier_candidates


def test_parse_supplier_candidates_maps_fields():
    offers = [
        {
            "companyName": "清河县碎梦汽车配件有限公司",
            "title": "十一层雨刮器胶条",
            "link": "https://detail.1688.com/offer/1044876429650.html",
            "imageUrl": "https://cbu01.alicdn.com/demo.jpg",
            "price": "11.19",
            "normalizationScore": "0.47900980710983276",
            "monthSold": "100+",
        }
    ]
    items = parse_supplier_candidates(offers, limit=5)
    assert len(items) == 1
    assert items[0]["supplier_name"] == "清河县碎梦汽车配件有限公司"
    assert items[0]["price_text"] == "¥11.19"
    assert items[0]["match_score"] == 47.9
    assert items[0]["product_url"].startswith("https://detail.1688.com/")


def test_parse_supplier_candidates_limits_to_five():
    offers = [{"companyName": f"供应商{i}", "title": f"商品{i}", "price": "1"} for i in range(10)]
    items = parse_supplier_candidates(offers, limit=5)
    assert len(items) == 5
