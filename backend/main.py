from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import router as api_router
from collector.ozon.browser_session import shutdown_ozon_browser_session
from config import get_cors_origins
import database


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    try:
        yield
    finally:
        shutdown_ozon_browser_session()


app = FastAPI(title="Amazon Workflow V1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
