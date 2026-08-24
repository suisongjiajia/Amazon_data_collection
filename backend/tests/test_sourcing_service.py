from services import sourcing_service


def test_search_suppliers_by_image_uses_1688_client(monkeypatch) -> None:
    family = {
        "id": 3,
        "main_image_url": "https://ir-20.ozonstatic.cn/demo.jpg",
        "title": "RD5 雨刮片",
    }
    candidates = [
        {
            "supplier_name": "供应商A",
            "shop_name": "供应商A",
            "product_title": "雨刮器",
            "product_url": "https://detail.1688.com/offer/1.html",
            "image_url": "https://cbu01.alicdn.com/1.jpg",
            "price_text": "¥11.19",
            "match_score": 47.9,
            "status": "candidate",
            "raw_payload": {"offerId": "1"},
        }
    ]

    monkeypatch.setattr(sourcing_service, "get_ozon_product_family", lambda _id: family)
    monkeypatch.setattr(
        sourcing_service,
        "create_sourcing_task",
        lambda family_id, image_url: {"id": 9, "task_no": "SRC-TEST"},
    )
    monkeypatch.setattr(
        sourcing_service,
        "finish_sourcing_task",
        lambda task_id, **kwargs: {"id": task_id, **kwargs},
    )
    monkeypatch.setattr(
        sourcing_service,
        "save_supplier_candidates",
        lambda family_id, items, sourcing_task_id=None: [
            {"id": 1, **items[0], "raw_product_family_id": family_id}
        ],
    )

    class StubClient:
        def search_suppliers_by_image_url(self, image_url: str):
            assert image_url == family["main_image_url"]
            return candidates

    monkeypatch.setattr(sourcing_service, "Alibaba1688Client", lambda: StubClient())

    result = sourcing_service.search_suppliers_by_image(3)
    assert result["task"]["status"] == "completed"
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["supplier_name"] == "供应商A"
