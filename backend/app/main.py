from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.outfit_routes import router as outfit_router
from app.core.config import settings
from app.core.observability import observe_request

settings.uploads_dir.mkdir(parents=True, exist_ok=True)

def repair_missing_embeddings():
    from app.repositories.factory import build_closet_repository
    from app.services.embedding_retry import EmbeddingRetry
    return EmbeddingRetry(build_closet_repository()).run_once(limit=3)


async def embedding_retry_loop(stop):
    while not stop.is_set():
        try:
            if settings.ai_api_key:
                await asyncio.to_thread(repair_missing_embeddings)
        except Exception as error:
            # No API keys, request payloads or signed URLs in background logs.
            print(f"embedding_retry loop_error={type(error).__name__}",flush=True)
        try:await asyncio.wait_for(stop.wait(),timeout=30)
        except asyncio.TimeoutError:pass


@asynccontextmanager
async def lifespan(app):
    stop=asyncio.Event()
    task=asyncio.create_task(embedding_retry_loop(stop))
    try:yield
    finally:
        stop.set()
        await task


app = FastAPI(title=settings.app_name,lifespan=lifespan)

from fastapi.responses import JSONResponse
from app.repositories.read_retry import DatabaseReadUnavailable


@app.exception_handler(DatabaseReadUnavailable)
async def database_read_unavailable(request, error):
    return JSONResponse(status_code=503, content={
        "detail": "Could not read your item because the database connection was interrupted. Please try again."
    }, headers={"Retry-After": "2"})


if settings.allowed_origins:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def request_observability_middleware(request, call_next):
    return await observe_request(request, call_next)


app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")
app.include_router(router)
app.include_router(outfit_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "env": settings.app_env}
