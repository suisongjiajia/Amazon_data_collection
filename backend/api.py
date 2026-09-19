from fastapi import APIRouter, File, Form, UploadFile
from typing import Any

from api_errors import handle_api_errors
import database
from schemas import (
    CollectRequest,
    ListingDraftCreateRequest,
    ListingDraftUpdateRequest,
    ListingDraftVariantUpdateRequest,
    OzonCollectionRequest,
    OzonCollectUrlRequest,
    OzonPublishRequest,
    AiProductEditRequest,
    SuggestPriceRequest,
    RehostImagesRequest,
    ProductCreateRequest,
    ProductEditUpdateRequest,
    ProductEditVariantUpdateRequest,
    PublishTaskCreateRequest,
    ReviewDecisionRequest,
    ReviewPriceUpdateRequest,
    SelectionCreateRequest,
    SelectionVariantScopeUpdateRequest,
    ShopPipelineStartRequest,
    ShopPipelineFromCollectionRequest,
    SourcingSearchRequest,
)
from services import catalog_service, collection_service, draft_service, publish_service
from services import ozon_collection_service, ozon_publish_service, product_edit_service, review_service, sourcing_service
from services import ai_product_edit_service, ozon_pricing_service, publish_auto_service, shop_pipeline_service
from integrations.aliyun_oss import rehost_image_urls, upload_local_images
from integrations.aliyun_oss.client import OssError
from db.ozon_catalog import get_ozon_product_family
from services.sourcing_service import _enrich_ozon_family_for_display

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, Any]:
    try:
        from db.connection import get_connection

        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "degraded", "database": str(exc)}


@router.get("/ozon/health")
def ozon_health() -> dict[str, Any]:
    from services.ozon_health_service import get_ozon_runtime_health

    return get_ozon_runtime_health()


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


# --- Ozon workflow ---


@router.post("/ozon/collect")
def collect_ozon_url(request: OzonCollectUrlRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_collection_service.run_ozon_url_collection(
            request.url,
            max_products=request.max_products,
        ),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/ozon/shop-popular")
def collect_ozon_shop_popular(request: ShopPipelineStartRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_collection_service.run_ozon_shop_popular_collection(
            request.shop_url,
            top_n=request.top_n,
        ),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/shop-pipeline/start")
def start_shop_pipeline(request: ShopPipelineStartRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: shop_pipeline_service.start_shop_pipeline(
            request.shop_url,
            top_n=request.top_n,
        ),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/shop-pipeline/from-collection")
def start_shop_pipeline_from_collection(request: ShopPipelineFromCollectionRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: shop_pipeline_service.start_pipeline_from_collection_task(
            request.collection_task_id,
            limit=request.limit,
        ),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/shop-pipeline/jobs")
def list_shop_pipeline_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return shop_pipeline_service.list_jobs(limit)


@router.get("/shop-pipeline/jobs/{job_id}")
def get_shop_pipeline_job(job_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: shop_pipeline_service.get_job(job_id),
        value_error_status=404,
    )


@router.post("/shop-pipeline/jobs/{job_id}/retry-failed")
def retry_shop_pipeline_failed(job_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: shop_pipeline_service.retry_failed_items(job_id),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/shop-pipeline/items/{item_id}/retry")
def retry_shop_pipeline_item(item_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: shop_pipeline_service.retry_item(item_id),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/ozon/collections")
def create_ozon_collection(request: OzonCollectionRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_collection_service.run_ozon_collection_task(
            request.strategy_type,
            request.strategy_params,
            source_url=request.source_url,
        ),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/ozon/collections")
def list_ozon_collections(limit: int = 50) -> list[dict[str, Any]]:
    return ozon_collection_service.list_tasks(limit)


@router.post("/ozon/collections/{task_id}/retry")
def retry_ozon_collection(task_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_collection_service.retry_collection_task(task_id),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/ozon/products")
def list_ozon_products(limit: int = 100) -> list[dict[str, Any]]:
    return ozon_collection_service.list_families(limit)


@router.post("/ozon/products/{family_id}/resolve-category")
def resolve_ozon_product_category(family_id: int) -> dict[str, Any]:
    from services.ozon_category_resolve_service import resolve_category_for_family

    return handle_api_errors(
        lambda: resolve_category_for_family(family_id, force=True),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/sourcing/search")
def search_sourcing(request: SourcingSearchRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: sourcing_service.search_suppliers_by_image(request.raw_product_family_id),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/sourcing/tasks")
def list_sourcing_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return sourcing_service.list_tasks(limit)


@router.get("/sourcing/candidates")
def list_sourcing_candidates(
    raw_product_family_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return sourcing_service.list_candidates(raw_product_family_id, limit)


@router.get("/sourcing/detail/{raw_product_family_id}")
def get_sourcing_detail(raw_product_family_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: sourcing_service.get_sourcing_detail(raw_product_family_id),
        value_error_status=404,
    )


@router.post("/sourcing/candidates/{candidate_id}/select")
def select_sourcing_candidate(candidate_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: sourcing_service.select_candidate(candidate_id),
        value_error_status=404,
    )


@router.post("/sourcing/candidates/{candidate_id}/unselect")
def unselect_sourcing_candidate(candidate_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: sourcing_service.unselect_candidate(candidate_id),
        value_error_status=404,
    )


@router.post("/product-edits/ai-generate")
def ai_generate_product_edit(request: AiProductEditRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ai_product_edit_service.generate_product_edit(
            request.raw_product_family_id,
            rehost_images=request.rehost_images,
        ),
        value_error_status=404,
        runtime_error_status=502,
    )


@router.post("/product-edits/suggest-price")
def suggest_product_price(request: SuggestPriceRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_pricing_service.suggest_price_for_family(request.raw_product_family_id),
        value_error_status=400,
    )


@router.post("/product-edits/rehost-images")
def rehost_product_images(request: RehostImagesRequest) -> dict[str, Any]:
    def _action() -> dict[str, Any]:
        images = list(request.images or [])
        sku = request.sku or "item"
        if request.raw_product_family_id is not None:
            family = get_ozon_product_family(request.raw_product_family_id)
            product = _enrich_ozon_family_for_display(family)
            if not images:
                images = list(product.get("images") or [])
                if product.get("main_image_url") and product["main_image_url"] not in images:
                    images = [product["main_image_url"], *images]
            sku = f"OZON-{product.get('external_id') or request.raw_product_family_id}"
        if not images:
            raise ValueError("没有可转存的图片")
        try:
            return rehost_image_urls(images, sku=sku)
        except OssError as exc:
            raise RuntimeError(str(exc)) from exc

    return handle_api_errors(_action, value_error_status=400, runtime_error_status=502)


@router.post("/product-edits/upload-images")
async def upload_product_images(
    files: list[UploadFile] = File(...),
    sku: str = Form("item"),
) -> dict[str, Any]:
    from fastapi import HTTPException

    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的图片")
    if len(files) > 15:
        raise HTTPException(status_code=400, detail="单次最多上传 15 张图片")

    payload: list[tuple[str, bytes, str]] = []
    for item in files:
        data = await item.read()
        payload.append(
            (
                item.filename or "image.jpg",
                data,
                item.content_type or "image/jpeg",
            )
        )

    try:
        return upload_local_images(payload, sku=sku or "item")
    except OssError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/product-edits")
def create_product_edit(raw_product_family_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.create_edit(raw_product_family_id),
        value_error_status=404,
    )


@router.get("/product-edits")
def list_product_edits(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return product_edit_service.list_edits(status, limit)


@router.get("/product-edits/{edit_id}")
def get_product_edit(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.get_edit(edit_id),
        value_error_status=404,
    )


@router.patch("/product-edits/{edit_id}")
def update_product_edit(edit_id: int, request: ProductEditUpdateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.update_edit(
            edit_id,
            title=request.title,
            description=request.description,
            bullet_points=request.bullet_points,
            images=request.images,
            attributes=request.attributes,
        ),
        value_error_status=404,
    )


@router.delete("/product-edits/{edit_id}")
def delete_product_edit(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.delete_edit(edit_id),
        value_error_status=400,
    )


@router.post("/product-edits/{edit_id}/build-listing")
def build_product_edit_listing(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.build_listing(edit_id),
        value_error_status=400,
    )


@router.post("/product-edits/{edit_id}/resolve-category")
def resolve_product_edit_category(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.resolve_category(edit_id, force=True),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/product-edits/{edit_id}/listing-preview")
def preview_product_edit_listing(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.preview_edit_listing(edit_id),
        value_error_status=404,
    )


@router.post("/product-edits/{edit_id}/submit-review")
def submit_product_edit_review(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.submit_for_review(edit_id),
        value_error_status=400,
    )


@router.post("/product-edits/{edit_id}/reopen")
def reopen_product_edit(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.reopen_edit(edit_id),
        value_error_status=400,
    )


@router.patch("/product-edit-variants/{variant_id}")
def update_product_edit_variant(
    variant_id: int,
    request: ProductEditVariantUpdateRequest,
) -> dict[str, Any]:
    return handle_api_errors(
        lambda: product_edit_service.update_variant(
            variant_id,
            title=request.title,
            price=request.price,
            quantity=request.quantity,
            image_url=request.image_url,
            variant_attributes=request.variant_attributes,
        ),
        value_error_status=404,
    )


@router.get("/reviews")
def list_reviews(edit_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return review_service.list_records(edit_id, limit)


@router.get("/reviews/{edit_id}/listing")
def get_review_listing(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: review_service.get_listing_for_review(edit_id),
        value_error_status=404,
    )


@router.patch("/reviews/{edit_id}/prices")
def update_review_prices(edit_id: int, request: ReviewPriceUpdateRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: review_service.update_prices(
            edit_id,
            apply_all_price=request.apply_all_price,
            variant_prices=(
                [item.model_dump() for item in request.variant_prices]
                if request.variant_prices
                else None
            ),
        ),
        value_error_status=400,
    )


@router.post("/reviews/{edit_id}/approve")
def approve_review(edit_id: int, request: ReviewDecisionRequest) -> dict[str, Any]:
    def _action() -> dict[str, Any]:
        if request.auto_publish:
            return publish_auto_service.approve_and_auto_publish(
                edit_id,
                note=request.note,
                reviewer=request.reviewer,
            )
        return review_service.approve(edit_id, note=request.note, reviewer=request.reviewer)

    return handle_api_errors(_action, value_error_status=400, runtime_error_status=502)


@router.post("/reviews/{edit_id}/reject")
def reject_review(edit_id: int, request: ReviewDecisionRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: review_service.reject(edit_id, note=request.note, reviewer=request.reviewer),
        value_error_status=400,
    )


@router.post("/ozon/publish-tasks")
def create_ozon_publish_task(request: OzonPublishRequest) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_publish_service.publish_edit(
            request.edit_id,
            shop_name=request.shop_name,
            simulate=request.simulate,
            auto_follow=request.auto_follow and not request.simulate,
        ),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.get("/ozon/publish-tasks")
def list_ozon_publish_tasks(limit: int = 50) -> list[dict[str, Any]]:
    return ozon_publish_service.list_tasks(limit)


@router.get("/ozon/publish-tasks/{task_id}")
def get_ozon_publish_task(task_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_publish_service.get_task(task_id),
        value_error_status=404,
    )


@router.post("/ozon/publish-tasks/{task_id}/refresh-status")
def refresh_ozon_publish_task_status(task_id: int) -> dict[str, Any]:
    def _run() -> dict[str, Any]:
        task = ozon_publish_service.refresh_import_status(task_id)
        status = str(task.get("status") or "")
        # 手动拉取后若仍未可售，自动挂上后台跟进闭环
        if status in {"awaiting_pull", "pushed", "partial", "submitted", "running"}:
            edit_id = int(task.get("edit_id") or 0)
            if edit_id:
                publish_auto_service.start_publish_follow(int(task["id"]), edit_id)
        return task

    return handle_api_errors(
        _run,
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/ozon/publish-tasks/reopen-edit/{edit_id}")
def reopen_edit_from_publish(edit_id: int) -> dict[str, Any]:
    return handle_api_errors(
        lambda: ozon_publish_service.reopen_edit_from_publish(edit_id),
        value_error_status=400,
    )


@router.post("/ozon/publish-tasks/republish/{edit_id}")
def republish_listed_edit(edit_id: int) -> dict[str, Any]:
    """已上架成功：重新生成 Listing（修图库等）并推送更新。"""
    return handle_api_errors(
        lambda: ozon_publish_service.republish_listed_edit(edit_id, auto_follow=True),
        value_error_status=400,
        runtime_error_status=502,
    )


@router.post("/ozon/publish-tasks/ai-heal/{edit_id}")
def ai_heal_and_republish(edit_id: int) -> dict[str, Any]:
    """发布失败后：规则修复 + AI 修复尺寸/字典属性，并自动重推。"""
    return handle_api_errors(
        lambda: publish_auto_service.heal_and_republish(edit_id, auto_follow=True),
        value_error_status=400,
        runtime_error_status=502,
    )
