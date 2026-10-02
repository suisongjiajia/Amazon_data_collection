from services.ozon_variant_cost_match import (
    match_cost_by_listing_title,
    parse_listing_spec,
    parse_raw_1688_spec,
)


def test_steps_parse_chinese_layers_and_35_45_height():
    assert parse_listing_spec("五层缓步楼梯（黄绿）高45CM")["steps"] == 5
    assert parse_listing_spec("四层缓步楼梯高35CM")["steps"] == 4
    assert parse_listing_spec("Лестница, 5 ступеней, высота 45 см")["steps"] == 5


def test_cover_raw_not_polluted_by_family_title():
    row = {
        "external_id": "6064642581426",
        "title": "宠物楼梯家用小型犬猫咪爬梯",
        "size": "可拆洗替换布套（五层/不含楼梯）可备注颜色",
        "color": "可拆洗-宠物楼梯",
        "price_text": "18",
        "variant_attributes": {"weight_g": 200},
    }
    spec = parse_raw_1688_spec(row)
    assert spec["is_cover"] is True
    assert spec["steps"] == 5
    assert spec["cost"] == 18.0


def test_five_step_stair_not_matched_to_cheapest_cover():
    family = {
        "variants": [
            {
                "external_id": "6064642581424",
                "title": "宠物楼梯",
                "size": "可拆洗替换布套（三层/不含楼梯）",
                "price_text": "12",
                "variant_attributes": {"weight_g": 200},
            },
            {
                "external_id": "5930006142361",
                "title": "宠物楼梯",
                "size": "五层缓步楼梯（黄绿）高45CM",
                "price_text": "55.8",
                "variant_attributes": {"weight_g": 1680},
            },
            {
                "external_id": "5930006142355",
                "title": "宠物楼梯",
                "size": "五层缓步楼梯（灰色）高45CM",
                "price_text": "55.8",
                "variant_attributes": {"weight_g": 1680},
            },
        ]
    }
    matched = match_cost_by_listing_title(
        {
            "sku": "A1688-5930006142361",
            "title": "Лестница для питомцев, 5 ступеней, жёлто-зелёная, высота 45 см",
        },
        family,
    )
    assert matched is not None
    assert matched["matched_external_id"] == "5930006142361"
    assert matched["cost"] == 55.8
    assert matched["weight_g"] == 1680
