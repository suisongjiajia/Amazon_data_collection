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


class OzonCollectionRequest(BaseModel):
    strategy_type: str
    strategy_params: dict[str, Any] = Field(default_factory=dict)
    source_url: str = ""


class OzonCollectUrlRequest(BaseModel):
    url: str
    max_products: int | None = None


class ShopPipelineStartRequest(BaseModel):
    shop_url: str
    top_n: int | None = 50


class Alibaba1688ShopCollectRequest(BaseModel):
    shop_url: str
    top_n: int | None = 50


class ShopPipelineFromCollectionRequest(BaseModel):
    collection_task_id: int
    limit: int | None = None


class SourcingSearchRequest(BaseModel):
    raw_product_family_id: int


class ProductEditUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    bullet_points: list[str] | None = None
    images: list[str] | None = None
    attributes: dict[str, Any] | None = None


class ProductEditVariantUpdateRequest(BaseModel):
    title: str | None = None
    price: float | None = None
    quantity: int | None = None
    image_url: str | None = None
    variant_attributes: dict[str, Any] | None = None


class ReviewDecisionRequest(BaseModel):
    note: str | None = None
    reviewer: str | None = "owner"
    auto_publish: bool = True


class ReviewVariantPriceItem(BaseModel):
    variant_id: int
    price: float


class ReviewPriceUpdateRequest(BaseModel):
    """审核中改价：可按变体分别改，或填 apply_all_price 统一改所有变体。"""
    apply_all_price: float | None = None
    variant_prices: list[ReviewVariantPriceItem] | None = None


class ReviewVariantEditItem(BaseModel):
    variant_id: int
    price: float | None = None
    color: str | None = None
    quantity: int | None = None
    title: str | None = None
    size: str | None = None
    image_url: str | None = None
    images: list[str] | None = None
    net_depth_mm: int | None = None
    net_width_mm: int | None = None
    net_height_mm: int | None = None


class ReviewContentUpdateRequest(BaseModel):
    """审核中心直接改包裹尺寸、净品尺寸、颜色和价格。"""
    depth_mm: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    weight_g: int | None = None
    net_depth_mm: int | None = None
    net_width_mm: int | None = None
    net_height_mm: int | None = None
    images: list[str] | None = None
    variant_aspect: str | None = None
    variants: list[ReviewVariantEditItem] | None = None


class OzonPublishRequest(BaseModel):
    edit_id: int
    shop_name: str | None = None
    simulate: bool = True
    auto_follow: bool = True


class AiProductEditRequest(BaseModel):
    raw_product_family_id: int
    rehost_images: bool = True


class SuggestPriceRequest(BaseModel):
    raw_product_family_id: int


class RehostImagesRequest(BaseModel):
    raw_product_family_id: int | None = None
    images: list[str] | None = None
    sku: str | None = None
