from services import catalog_service


def test_create_selection_delegates_to_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_selection(
        raw_product_family_id: int,
        *,
        owner: str | None = None,
        remark: str | None = None,
        score: float | None = None,
    ):
        captured.update(
            {
                "raw_product_family_id": raw_product_family_id,
                "owner": owner,
                "remark": remark,
                "score": score,
            }
        )
        return {"id": 10}

    monkeypatch.setattr(
        catalog_service.selection_repository,
        "create_selection",
        fake_create_selection,
    )

    result = catalog_service.create_selection(5, owner="alice", remark="ok", score=7.5)

    assert result == {"id": 10}
    assert captured == {
        "raw_product_family_id": 5,
        "owner": "alice",
        "remark": "ok",
        "score": 7.5,
    }


def test_update_selection_variant_scope_delegates_to_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_update_selection_variant_scope(selection_id: int, raw_product_variant_ids: list[int]):
        captured.update(
            {
                "selection_id": selection_id,
                "raw_product_variant_ids": raw_product_variant_ids,
            }
        )
        return {"id": selection_id}

    monkeypatch.setattr(
        catalog_service.selection_repository,
        "update_selection_variant_scope",
        fake_update_selection_variant_scope,
    )

    result = catalog_service.update_selection_variant_scope(3, [11, 12])

    assert result == {"id": 3}
    assert captured == {
        "selection_id": 3,
        "raw_product_variant_ids": [11, 12],
    }


def test_create_product_from_selection_delegates_to_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_product_from_selection(
        selection_id: int,
        *,
        spu_code: str | None = None,
        product_name: str | None = None,
        brand: str | None = None,
        target_marketplace: str | None = None,
        default_cost: float | None = None,
        stock_qty: int = 0,
    ):
        captured.update(
            {
                "selection_id": selection_id,
                "spu_code": spu_code,
                "product_name": product_name,
                "brand": brand,
                "target_marketplace": target_marketplace,
                "default_cost": default_cost,
                "stock_qty": stock_qty,
            }
        )
        return {"id": 20}

    monkeypatch.setattr(
        catalog_service.product_repository,
        "create_product_from_selection",
        fake_create_product_from_selection,
    )

    result = catalog_service.create_product_from_selection(
        3,
        spu_code="SPU-1",
        product_name="Demo Product",
        brand="Demo Brand",
        target_marketplace="www.amazon.com",
        default_cost=12.5,
        stock_qty=6,
    )

    assert result == {"id": 20}
    assert captured == {
        "selection_id": 3,
        "spu_code": "SPU-1",
        "product_name": "Demo Product",
        "brand": "Demo Brand",
        "target_marketplace": "www.amazon.com",
        "default_cost": 12.5,
        "stock_qty": 6,
    }
