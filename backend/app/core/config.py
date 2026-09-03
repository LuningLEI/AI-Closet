from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"


def _load_env_file() -> None:
    if not ENV_PATH.exists():
        return

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


_load_env_file()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI Closet API")
    app_env: str = os.getenv("APP_ENV", "development")
    web_origin: str = os.getenv("WEB_ORIGIN", "http://localhost:3000")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", str(BASE_DIR / "data" / "uploads")))
    items_path: Path = Path(os.getenv("ITEMS_PATH", str(BASE_DIR / "data" / "items.json")))
    recognition_records_path: Path = Path(
        os.getenv("RECOGNITION_RECORDS_PATH", str(BASE_DIR / "data" / "recognition_records.json"))
    )
    recognition_jobs_path: Path = Path(
        os.getenv("RECOGNITION_JOBS_PATH", str(BASE_DIR / "data" / "recognition_jobs.json"))
    )
    item_feature_snapshots_path: Path = Path(
        os.getenv("ITEM_FEATURE_SNAPSHOTS_PATH", str(BASE_DIR / "data" / "item_feature_snapshots.json"))
    )
    storage_mode: str = os.getenv("STORAGE_MODE", "local")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    supabase_url: str | None = os.getenv("SUPABASE_URL") or None
    supabase_key: str | None = os.getenv("SUPABASE_KEY") or None
    supabase_service_role_key: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None
    supabase_storage_bucket: str = os.getenv("SUPABASE_STORAGE_BUCKET", "closet-images")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    openai_vision_model: str = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    openai_vision_detail: str = os.getenv("OPENAI_VISION_DETAIL", "low")
    openai_agent_planner_model: str = os.getenv("OPENAI_AGENT_PLANNER_MODEL", "gpt-4.1-mini")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    openai_embedding_dimensions: int = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))
    recognition_worker_batch_size: int = int(os.getenv("RECOGNITION_WORKER_BATCH_SIZE", "3"))
    recognition_worker_poll_seconds: float = float(os.getenv("RECOGNITION_WORKER_POLL_SECONDS", "2"))
    recognition_worker_max_attempts: int = int(os.getenv("RECOGNITION_WORKER_MAX_ATTEMPTS", "3"))
    recognition_worker_job_timeout_seconds: int = int(os.getenv("RECOGNITION_WORKER_JOB_TIMEOUT_SECONDS", "120"))
    recognition_worker_retry_base_seconds: int = int(os.getenv("RECOGNITION_WORKER_RETRY_BASE_SECONDS", "10"))
    recognition_worker_retry_max_seconds: int = int(os.getenv("RECOGNITION_WORKER_RETRY_MAX_SECONDS", "300"))
    require_auth_for_mutations: bool = os.getenv("REQUIRE_AUTH_FOR_MUTATIONS", "true").lower() in {"1", "true", "yes"}


settings = Settings()
