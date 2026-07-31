import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.retention_worker import run_retention_worker
from app.services.security import bootstrap_admin, validate_auth_secret

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_auth_secret(settings)
    with SessionLocal() as db:
        bootstrap_admin(db)
    retention_stop = asyncio.Event()
    retention_task = (
        asyncio.create_task(run_retention_worker(retention_stop, settings=settings))
        if settings.talent_retention_worker_enabled
        else None
    )
    try:
        yield
    finally:
        if retention_task is not None:
            retention_stop.set()
            await retention_task

_docs_enabled = settings.app_env == "development"

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}
