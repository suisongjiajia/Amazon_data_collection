from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from collector import AmazonCollector
import database


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Amazon Workflow V1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CollectRequest(BaseModel):
    url: str


class SelectionCreateRequest(BaseModel):
    raw_product_id: int
    owner: str | None = None
    remark: str | None = None
    score: float | None = None


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


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        database.check_db()
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "degraded", "database": str(exc)}


@app.post("/api/collect")
def collect(request: CollectRequest) -> list[dict]:
    try:
        products = AmazonCollector().collect(request.url)
        payload = [product.to_dict() for product in products]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        database.save_products(products)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Collect succeeded but saving failed: {exc}",
        ) from exc

    return payload


@app.post("/api/collections")
def create_collection(request: CollectRequest) -> dict[str, Any]:
    task = database.create_collection_task(request.url)

    try:
        products = AmazonCollector().collect(request.url)
        snapshots = database.save_raw_products(int(task["id"]), products)
        task = database.finish_collection_task(
            int(task["id"]),
            status="completed",
            total_count=len(products),
            success_count=len(products),
            fail_count=0,
        )
        return {
            "task": task,
            "snapshots": snapshots,
        }
    except ValueError as exc:
        database.finish_collection_task(
            int(task["id"]),
            status="failed",
            total_count=0,
            success_count=0,
            fail_count=1,
            error_message=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        database.finish_collection_task(
            int(task["id"]),
            status="failed",
            total_count=0,
            success_count=0,
            fail_count=1,
            error_message=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        database.finish_collection_task(
            int(task["id"]),
            status="failed",
            total_count=0,
            success_count=0,
            fail_count=1,
            error_message=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/collections")
def list_collections(limit: int = 50) -> list[dict[str, Any]]:
    return database.list_collection_tasks(limit)


@app.get("/api/collections/{task_id}")
def get_collection(task_id: int) -> dict[str, Any]:
    try:
        return {
            "task": database.get_collection_task(task_id),
            "snapshots": database.get_raw_products_for_task(task_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/raw-products")
def list_raw_products(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_raw_products(limit)


@app.post("/api/selections")
def create_selection(request: SelectionCreateRequest) -> dict[str, Any]:
    try:
        return database.create_selection(
            request.raw_product_id,
            owner=request.owner,
            remark=request.remark,
            score=request.score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/selections")
def list_selections(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_selections(limit)


@app.post("/api/products")
def create_product(request: ProductCreateRequest) -> dict[str, Any]:
    try:
        return database.create_product_from_selection(
            request.selection_id,
            spu_code=request.spu_code,
            product_name=request.product_name,
            brand=request.brand,
            target_marketplace=request.target_marketplace,
            default_cost=request.default_cost,
            stock_qty=request.stock_qty,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/products")
def list_products(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_products(limit)


@app.post("/api/listing-drafts")
def create_listing_draft(request: ListingDraftCreateRequest) -> dict[str, Any]:
    try:
        return database.create_listing_draft(
            request.product_master_id,
            shop_name=request.shop_name,
            marketplace=request.marketplace,
            title=request.title,
            price=request.price,
            quantity=request.quantity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/listing-drafts")
def list_listing_drafts(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_listing_drafts(limit)


@app.patch("/api/listing-drafts/{draft_id}")
def update_listing_draft(draft_id: int, request: ListingDraftUpdateRequest) -> dict[str, Any]:
    try:
        return database.update_listing_draft(
            draft_id,
            title=request.title,
            bullet_points=request.bullet_points,
            description=request.description,
            search_terms=request.search_terms,
            attributes=request.attributes,
            status=request.status,
            change_note=request.change_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/listing-draft-variants/{draft_variant_id}")
def update_listing_draft_variant(
    draft_variant_id: int,
    request: ListingDraftVariantUpdateRequest,
) -> dict[str, Any]:
    try:
        return database.update_listing_draft_variant(
            draft_variant_id,
            price=request.price,
            quantity=request.quantity,
            fulfillment_channel=request.fulfillment_channel,
            external_product_id=request.external_product_id,
            external_product_id_type=request.external_product_id_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/publish-tasks")
def create_publish_task(request: PublishTaskCreateRequest) -> dict[str, Any]:
    try:
        return database.create_publish_task(
            request.draft_ids,
            shop_name=request.shop_name,
            marketplace=request.marketplace,
            simulate=request.simulate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/publish-tasks")
def list_publish_tasks(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_publish_tasks(limit)


@app.get("/api/listing-live")
def list_listing_live(limit: int = 100) -> list[dict[str, Any]]:
    return database.list_listing_live(limit)
