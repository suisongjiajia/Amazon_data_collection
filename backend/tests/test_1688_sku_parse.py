from collector.alibaba1688.sku_parse import (
    looks_like_size,
    looks_like_style,
    merge_pack_into_skus,
    parse_sku_selector_payload,
)


def _pet_bed_dual_payload() -> dict:
    """规格(棕/灰) × 颜色标签实为尺码(S/M/L) = 6 组合。"""
    return {
        "data": {
            "skuProps": [
                {
                    "prop": "规格",
                    "value": [
                        {
                            "name": "棕色小熊",
                            "imageUrl": "//cbu01.alicdn.com/img/ibank/brown.jpg",
                        },
                        {
                            "name": "灰色长耳朵",
                            "imageUrl": "//cbu01.alicdn.com/img/ibank/grey.jpg",
                        },
                    ],
                },
                {
                    "prop": "颜色",
                    "value": [
                        {"name": "S(33*30*32CM) 建议7斤内宠物"},
                        {"name": "M(40*35*38CM) 建议15斤内宠物"},
                        {"name": "L(45*40*45CM) 建议25斤内宠物"},
                    ],
                },
            ],
            "skuMap": {
                "棕色小熊&gt;S(33*30*32CM) 建议7斤内宠物": {
                    "skuId": "1001",
                    "specAttrs": "棕色小熊&gt;S(33*30*32CM) 建议7斤内宠物",
                    "discountPrice": "19.00",
                },
                "棕色小熊&gt;M(40*35*38CM) 建议15斤内宠物": {
                    "skuId": "1002",
                    "specAttrs": "棕色小熊&gt;M(40*35*38CM) 建议15斤内宠物",
                    "discountPrice": "23.80",
                },
                "棕色小熊&gt;L(45*40*45CM) 建议25斤内宠物": {
                    "skuId": "1003",
                    "specAttrs": "棕色小熊&gt;L(45*40*45CM) 建议25斤内宠物",
                    "discountPrice": "26.80",
                },
                "灰色长耳朵&gt;S(33*30*32CM) 建议7斤内宠物": {
                    "skuId": "1004",
                    "specAttrs": "灰色长耳朵&gt;S(33*30*32CM) 建议7斤内宠物",
                    "discountPrice": "19.00",
                },
                "灰色长耳朵&gt;M(40*35*38CM) 建议15斤内宠物": {
                    "skuId": "1005",
                    "specAttrs": "灰色长耳朵&gt;M(40*35*38CM) 建议15斤内宠物",
                    "discountPrice": "23.80",
                },
                "灰色长耳朵&gt;L(45*40*45CM) 建议25斤内宠物": {
                    "skuId": "1006",
                    "specAttrs": "灰色长耳朵&gt;L(45*40*45CM) 建议25斤内宠物",
                    "discountPrice": "26.80",
                },
            },
        }
    }


def test_looks_like_size_vs_style():
    assert looks_like_size("S(33*30*32CM) 建议7斤内宠物")
    assert looks_like_size("M(40*35*38CM) 建议15斤内宠物")
    assert looks_like_style("棕色小熊")
    assert looks_like_style("灰色长耳朵")
    assert not looks_like_size("棕色小熊")


def test_dual_axis_yields_six_skus_with_images():
    rows = parse_sku_selector_payload(_pet_bed_dual_payload())
    assert len(rows) == 6
    labels = {row["label"] for row in rows}
    assert any("棕色小熊" in label and "S(" in label for label in labels)
    assert any("灰色长耳朵" in label and "L(" in label for label in labels)
    brown = [row for row in rows if row["color"] == "棕色小熊"]
    grey = [row for row in rows if row["color"] == "灰色长耳朵"]
    assert len(brown) == 3
    assert len(grey) == 3
    assert all(row["image_url"].endswith("brown.jpg") for row in brown)
    assert all(row["image_url"].endswith("grey.jpg") for row in grey)
    assert all(row["size"] and "CM" in row["size"] for row in rows)
    assert {row["sku_id"] for row in rows} == {"1001", "1002", "1003", "1004", "1005", "1006"}


def test_does_not_flatten_props_into_five_fake_skus():
    """旧逻辑会把 2+3 个选项摊成 5 条，而不是 6 组合。"""
    rows = parse_sku_selector_payload(_pet_bed_dual_payload())
    names = {row["label"] for row in rows}
    assert "棕色小熊" not in names  # 必须是组合名
    assert len(rows) != 5


def test_merge_pack_by_size_text():
    skus = parse_sku_selector_payload(_pet_bed_dual_payload())
    pack_rows = [
        {
            "color": "S(33*30*32CM) 建议7斤内宠物",
            "length_cm": "33",
            "width_cm": "30",
            "height_cm": "32",
            "weight_g": "400",
        }
    ]
    merged = merge_pack_into_skus(skus, pack_rows)
    s_rows = [row for row in merged if row.get("size", "").startswith("S(")]
    assert len(s_rows) == 2
    assert all(row.get("weight_g") == "400" for row in s_rows)
