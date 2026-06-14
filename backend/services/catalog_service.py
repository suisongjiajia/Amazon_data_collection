from typing import Any

from repositories import product_repository, selection_repository


def create_selection(
    raw_product_family_id: int,
    *,
    owner: str | None = None,
    remark: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    return selection_repository.create_selection(
        raw_product_family_id,
        owner=owner,
        remark=remark,
        score=score,
    )


def update_selection_variant_scope(
    selection_id: int,
    raw_product_variant_ids: list[int],
) -> dict[str, Any]:
    return selection_repository.update_selection_variant_scope(
        selection_id,
        raw_product_variant_ids,
    )


def list_selections(limit: int = 100) -> list[dict[str, Any]]:
    return selection_repository.list_selections(limit)


def create_product_from_selection(
    selection_id: int,
    *,
    spu_code: str | None = None,
    product_name: str | None = None,
    brand: str | None = None,
    target_marketplace: str | None = None,
    default_cost: float | None = None,
    stock_qty: int = 0,
) -> dict[str, Any]:
    return product_repository.create_product_from_selection(
        selection_id,
        spu_code=spu_code,
        product_name=product_name,
        brand=brand,
        target_marketplace=target_marketplace,
        default_cost=default_cost,
        stock_qty=stock_qty,
    )


def list_products(limit: int = 100) -> list[dict[str, Any]]:
    return product_repository.list_products(limit)
