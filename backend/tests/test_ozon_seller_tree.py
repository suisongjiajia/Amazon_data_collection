from integrations.ozon_seller.seller_tree import parse_resolved_categories_payload


def test_parse_resolved_categories_object():
    payload = {
        "resolved_categories_by_sku": {
            "1873579696": {
                "description_category_id_level_2": "17027495",
                "description_category_id_level_3": "83250454",
                "description_category_id_level_4": "99447970",
                "description_type_id": "970860463",
            }
        }
    }
    resolved = parse_resolved_categories_payload(payload, "1873579696")
    assert resolved is not None
    assert resolved.description_category_id == "99447970"
    assert resolved.type_id == "970860463"


def test_parse_resolved_categories_list():
    payload = {
        "resolved_categories_by_sku": {
            "26720891541": [
                {
                    "description_category_id_level_2": "17027495",
                    "description_category_id_level_3": "88280454",
                    "description_category_id_level_4": "200001075",
                    "description_type_id": "971107021",
                }
            ]
        }
    }
    resolved = parse_resolved_categories_payload(payload, "26720891541")
    assert resolved is not None
    assert resolved.description_category_id == "200001075"
    assert resolved.type_id == "971107021"
