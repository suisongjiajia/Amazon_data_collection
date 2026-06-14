from services import draft_service


def test_create_listing_draft_delegates_to_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_listing_draft(
        product_master_id: int,
        *,
        shop_name: str,
        marketplace: str | None = None,
        title: str | None = None,
        price: float | None = None,
        quantity: int | None = None,
    ):
        captured.update(
            {
                "product_master_id": product_master_id,
                "shop_name": shop_name,
                "marketplace": marketplace,
                "title": title,
                "price": price,
                "quantity": quantity,
            }
        )
        return {"id": 3}

    monkeypatch.setattr(
        draft_service.draft_repository,
        "create_listing_draft",
        fake_create_listing_draft,
    )

    result = draft_service.create_listing_draft(
        12,
        shop_name="Demo Shop",
        marketplace="www.amazon.com",
        title="Draft title",
        price=19.99,
        quantity=8,
    )

    assert result == {"id": 3}
    assert captured == {
        "product_master_id": 12,
        "shop_name": "Demo Shop",
        "marketplace": "www.amazon.com",
        "title": "Draft title",
        "price": 19.99,
        "quantity": 8,
    }


def test_update_listing_draft_variant_delegates_to_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_update_listing_draft_variant(
        draft_variant_id: int,
        *,
        price: float | None = None,
        quantity: int | None = None,
        fulfillment_channel: str | None = None,
        external_product_id: str | None = None,
        external_product_id_type: str | None = None,
    ):
        captured.update(
            {
                "draft_variant_id": draft_variant_id,
                "price": price,
                "quantity": quantity,
                "fulfillment_channel": fulfillment_channel,
                "external_product_id": external_product_id,
                "external_product_id_type": external_product_id_type,
            }
        )
        return {"id": draft_variant_id}

    monkeypatch.setattr(
        draft_service.draft_repository,
        "update_listing_draft_variant",
        fake_update_listing_draft_variant,
    )

    result = draft_service.update_listing_draft_variant(
        44,
        price=29.99,
        quantity=9,
        fulfillment_channel="FBA",
        external_product_id="123456789012",
        external_product_id_type="UPC",
    )

    assert result == {"id": 44}
    assert captured == {
        "draft_variant_id": 44,
        "price": 29.99,
        "quantity": 9,
        "fulfillment_channel": "FBA",
        "external_product_id": "123456789012",
        "external_product_id_type": "UPC",
    }
