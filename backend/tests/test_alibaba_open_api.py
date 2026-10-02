from collector.alibaba1688.open_api import (
    is_idempotent_ok_payload,
    needs_relation_or_push,
    sign_request_hmac_sha1,
)
from collector.alibaba1688.open_product_detail import map_query_product_detail


def test_sign_request_hmac_sha1_stable():
    path = "param2/1/com.alibaba.fenxiao.crossborder/product.search.queryProductDetail/123456"
    params = {"access_token": "tok", "offerDetailParam": '{"offerId":1,"country":"en","outMemberId":"1"}'}
    a = sign_request_hmac_sha1(path, params, "secret")
    b = sign_request_hmac_sha1(path, params, "secret")
    assert a == b
    assert len(a) == 40
    assert a == a.upper()


def test_needs_relation_or_push_detects_permission_and_missing():
    assert needs_relation_or_push({"success": False, "message": "没有该商品的查询权限"})
    assert needs_relation_or_push({"result": {"success": False, "code": "SP0056", "message": "商品不存在"}})
    assert not needs_relation_or_push({"success": True, "productInfo": {"offerId": 1}})


def test_idempotent_ok_treats_already_related_as_success():
    assert is_idempotent_ok_payload({"success": True})
    assert is_idempotent_ok_payload({"message": "关系已存在"})
    assert is_idempotent_ok_payload({"error_message": "already exists"})


def test_map_query_product_detail_skus_and_images():
    payload = {
        "result": {
            "result": {
                "offerId": "5930006142361",
                "subject": "宠物楼梯黄绿五层",
                "subjectTrans": "Pet stairs yellow-green 5 steps",
                "imageList": ["https://cbu01.alicdn.com/img/ibank/demo1.jpg"],
                "productSkuInfos": [
                    {
                        "skuId": "111",
                        "specId": "aaa",
                        "price": "55.8",
                        "jxhyPrice": "55.8",
                        "skuAttributes": [
                            {
                                "attributeName": "颜色",
                                "value": "黄绿",
                                "skuImageUrl": "https://cbu01.alicdn.com/img/ibank/sku1.jpg",
                            },
                            {"attributeName": "规格", "value": "五层缓步楼梯高45CM"},
                        ],
                    },
                    {
                        "skuId": "222",
                        "price": "18",
                        "skuAttributes": [
                            {"attributeName": "颜色", "value": "布套"},
                            {"attributeName": "规格", "value": "五层换洗外套"},
                        ],
                    },
                ],
                "productShippingInfo": {"weight": "1.68"},
                "companyName": "测试工厂",
            }
        }
    }
    offer = map_query_product_detail(payload, source="open_api_cross_productInfo")
    assert offer.offer_id == "5930006142361"
    assert offer.title
    assert len(offer.skus) == 2
    assert offer.skus[0]["sku_id"] == "111"
    assert offer.skus[0]["color"] == "黄绿"
    assert "55.8" in str(offer.price_text)
    assert offer.shop_name == "测试工厂"
    assert offer.raw_payload.get("source") == "open_api_cross_productInfo"
