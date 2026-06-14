from typing import Any

from pydantic import BaseModel, Field


class CollectRequest(BaseModel):
    url: str


class SelectionCreateRequest(BaseModel):
    raw_product_family_id: int
    owner: str | None = None
    remark: str | None = None
    score: float | None = None


class SelectionVariantScopeUpdateRequest(BaseModel):
    raw_product_variant_ids: list[int] = Field(min_length=1)


class ProductCreateRequest(BaseModel):
    selection_id: int
    spu_code: str | None = None
    product_name: str | None = None
    brand: str | None = None
    target_marketplace: str | None = None
    default_cost: float | None = None
    stock_qty: int = 0


class ListingDraftCreateRequest(BaseModel):
    product_master_id: int
    shop_name: str
    marketplace: str | None = None
    title: str | None = None
    price: float | None = None
    quantity: int | None = None


class ListingDraftUpdateRequest(BaseModel):
    title: str | None = None
    bullet_points: list[str] | None = None
    description: str | None = None
    search_terms: str | None = None
    attributes: dict[str, Any] | None = None
    status: str | None = None
    change_note: str | None = None


class ListingDraftVariantUpdateRequest(BaseModel):
    price: float | None = None
    quantity: int | None = None
    fulfillment_channel: str | None = None
    external_product_id: str | None = None
    external_product_id_type: str | None = None


class PublishTaskCreateRequest(BaseModel):
    draft_ids: list[int] = Field(min_length=1)
    shop_name: str | None = None
    marketplace: str | None = None
    simulate: bool = True
