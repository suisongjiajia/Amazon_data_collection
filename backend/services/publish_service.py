from typing import Any

from repositories import publish_repository


def create_publish_task(
    draft_ids: list[int],
    *,
    shop_name: str | None = None,
    marketplace: str | None = None,
    simulate: bool = True,
) -> dict[str, Any]:
    return publish_repository.create_publish_task(
        draft_ids,
        shop_name=shop_name,
        marketplace=marketplace,
        simulate=simulate,
    )


def list_publish_tasks(limit: int = 100) -> list[dict[str, Any]]:
    return publish_repository.list_publish_tasks(limit)
