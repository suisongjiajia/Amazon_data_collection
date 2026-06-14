import database


def test_build_live_listing_record_uses_reference_asin() -> None:
    draft = {
        "id": 21,
        "attributes": {
            "reference_asin": "B0REALASIN1",
        },
    }
    draft_variant = {
        "variant_id": 31,
        "seller_sku": "SKU-001",
        "price": 29.99,
        "quantity": 5,
        "external_product_id": "123456789012",
    }
    payload = {
        "external_product_id": "123456789012",
    }

    record = database._build_live_listing_record(
        41,
        draft,
        draft_variant,
        "Demo Shop",
        "www.amazon.com",
        payload,
    )

    assert record["asin"] == "B0REALASIN1"
    assert record["seller_sku"] == "SKU-001"
    assert record["live_payload"] == payload
