from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import settings
from app.core.observability import observe_request

settings.uploads_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://127.0.0.1:3000", "http://localhost:3000"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_observability_middleware(request, call_next):
    return await observe_request(request, call_next)


app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")
app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "env": settings.app_env}
