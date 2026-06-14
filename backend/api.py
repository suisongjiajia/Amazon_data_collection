from typing import Any

from fastapi import APIRouter

from api_errors import handle_api_errors
import database
from schemas import (
    CollectRequest,
    ListingDraftCreateRequest,
    ListingDraftUpdateRequest,
    ListingDraftVariantUpdateRequest,
    ProductCreateRequest,
    PublishTaskCreateRequest,
    SelectionCreateRequest,
    SelectionVariantScopeUpdateRequest,
)
from services import catalog_service, collection_service, draft_service, publish_service

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    try:
        database.check_db()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "degraded", "database": str(exc)}


@router.post("/collect")
def collect(request: CollectRequest) -> list[dict]:
    return handle_api_errors(
        lambda: collection_service.collect_products(request.url),
        value_error_status=400,
        runtime_error_status=502,
        fallback_message="Collect succeeded but saving failed: {error}",
    )


@router.post("/collections")
def create_collection(request: CollectRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: collection_service.run_collection_task(request.url),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/collections")
def list_collections(limit: int = 50) -> list[dict[str, Any]]:
    return database.list_collection_tasks(limit)


@router.get("/collections/{task_id}")
def get_collection(task_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: {
            "task": database.get_collection_task(task_id),
            "families": database.get_raw_product_families_for_task(task_id),
        },
        value_error_status=404,
    )


@router.get("/raw-product-families")
def list_raw_product_families(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_raw_product_families(limit)


@router.post("/selections")
def create_selection(request: SelectionCreateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: catalog_service.create_selection(
            request.raw_product_family_id,
            owner=request.owner,
            remark=request.remark,
            score=request.score,
        ),
        value_error_status=404,
    )


@router.put("/selections/{selection_id}/variant-scope")
def update_selection_variant_scope(
    selection_id: int,
    request: SelectionVariantScopeUpdateRequest,
) -> dict[str, Any]:
    return handle_api_errors(
        lambda: catalog_service.update_selection_variant_scope(
            selection_id,
            request.raw_product_variant_ids,
        ),
        value_error_status=404,
    )


@router.get("/selections")
def list_selections(limit: int = 100) -> list[dict[str, Any]]:
    return catalog_service.list_selections(limit)


@router.post("/products")
def create_product(request: ProductCreateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: catalog_service.create_product_from_selection(
            request.selection_id,
            spu_code=request.spu_code,
            product_name=request.product_name,
            brand=request.brand,
            target_marketplace=request.target_marketplace,
            default_cost=request.default_cost,
            stock_qty=request.stock_qty,
        ),
        value_error_status=404,
    )


@router.get("/products")
def list_products(limit: int = 100) -> list[dict[str, Any]]:
    return catalog_service.list_products(limit)


@router.post("/listing-drafts")
def create_listing_draft(request: ListingDraftCreateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: draft_service.create_listing_draft(
            request.product_master_id,
            shop_name=request.shop_name,
            marketplace=request.marketplace,
            title=request.title,
            price=request.price,
            quantity=request.quantity,
        ),
        value_error_status=404,
    )


@router.get("/listing-drafts")
def list_listing_drafts(limit: int = 100) -> list[dict[str, Any]]:
    return draft_service.list_listing_drafts(limit)


@router.patch("/listing-drafts/{draft_id}")
def update_listing_draft(draft_id: int, request: ListingDraftUpdateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: draft_service.update_listing_draft(
            draft_id,
            title=request.title,
            bullet_points=request.bullet_points,
            description=request.description,
            search_terms=request.search_terms,
            attributes=request.attributes,
            status=request.status,
            change_note=request.change_note,
        ),
        value_error_status=404,
    )


@router.patch("/listing-draft-variants/{draft_variant_id}")
def update_listing_draft_variant(
    draft_variant_id: int,
    request: ListingDraftVariantUpdateRequest,
) -> dict[str, Any]:
    return handle_api_errors(
        lambda: draft_service.update_listing_draft_variant(
            draft_variant_id,
            price=request.price,
            quantity=request.quantity,
            fulfillment_channel=request.fulfillment_channel,
            external_product_id=request.external_product_id,
            external_product_id_type=request.external_product_id_type,
        ),
        value_error_status=404,
    )


@router.post("/publish-tasks")
def create_publish_task(request: PublishTaskCreateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: publish_service.create_publish_task(
            request.draft_ids,
            shop_name=request.shop_name,
            marketplace=request.marketplace,
            simulate=request.simulate,
        ),
        value_error_status=400,
    )


@router.get("/publish-tasks")
def list_publish_tasks(limit: int = 100) -> list[dict[str, Any]]:
    return publish_service.list_publish_tasks(limit)


@router.get("/listing-live")
def list_listing_live(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_listing_live(limit)
