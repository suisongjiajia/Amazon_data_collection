from services import publish_service


def test_create_publish_task_delegates_to_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_publish_task(
        draft_ids: list[int],
        *,
        shop_name: str | None = None,
        marketplace: str | None = None,
        simulate: bool = True,
    ):
        captured.update(
            {
                "draft_ids": draft_ids,
                "shop_name": shop_name,
                "marketplace": marketplace,
                "simulate": simulate,
            }
        )
        return {"id": 5}

    monkeypatch.setattr(
        publish_service.publish_repository,
        "create_publish_task",
        fake_create_publish_task,
    )

    result = publish_service.create_publish_task(
        [1, 2],
        shop_name="Demo Shop",
        marketplace="www.amazon.com",
        simulate=False,
    )

    assert result == {"id": 5}
    assert captured == {
        "draft_ids": [1, 2],
        "shop_name": "Demo Shop",
        "marketplace": "www.amazon.com",
        "simulate": False,
    }


def test_list_publish_tasks_delegates_to_repository(monkeypatch) -> None:
    monkeypatch.setattr(
        publish_service.publish_repository,
        "list_publish_tasks",
        lambda limit: [{"id": 7, "limit": limit}],
    )

    assert publish_service.list_publish_tasks(25) == [{"id": 7, "limit": 25}]
