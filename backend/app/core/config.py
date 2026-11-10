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


def _stage_api_key(explicit_name: str, base_url_name: str) -> str | None:
    explicit = os.getenv(explicit_name)
    if explicit:
        return explicit
    base_url = os.getenv(base_url_name, "").lower()
    if "huggingface.co" in base_url:
        return os.getenv("HF_TOKEN") or None
    if "novita.ai" in base_url:
        return os.getenv("NOVITA_API_KEY") or None
    return os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or None


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI Closet API")
    app_env: str = os.getenv("APP_ENV", "development")
    allowed_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv("ALLOWED_ORIGINS", "").split(",") if value.strip()
    )
    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", str(BASE_DIR / "data" / "uploads")))
    items_path: Path = Path(os.getenv("ITEMS_PATH", str(BASE_DIR / "data" / "items.json")))
    recognition_records_path: Path = Path(
        os.getenv("RECOGNITION_RECORDS_PATH", str(BASE_DIR / "data" / "recognition_records.json"))
    )
    recognition_jobs_path: Path = Path(
        os.getenv("RECOGNITION_JOBS_PATH", str(BASE_DIR / "data" / "recognition_jobs.json"))
    )
    item_edit_events_path: Path = Path(
        os.getenv("ITEM_EDIT_EVENTS_PATH", str(BASE_DIR / "data" / "item_edit_events.json"))
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
    ai_provider: str = os.getenv("AI_PROVIDER", "openai-compatible")
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    ai_api_key: str | None = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or None
    ai_allowed_models: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv("AI_ALLOWED_MODELS", "").split(",") if value.strip()
    )
    ai_chat_schema_mode: str = os.getenv("AI_CHAT_SCHEMA_MODE", "json-schema")
    openai_vision_model: str = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    openai_vision_detail: str = os.getenv("OPENAI_VISION_DETAIL", "low")
    recognition_ai_provider: str = os.getenv("RECOGNITION_AI_PROVIDER", os.getenv("AI_PROVIDER", "openai-compatible"))
    recognition_ai_base_url: str = os.getenv("RECOGNITION_AI_BASE_URL", os.getenv("AI_BASE_URL", "https://api.openai.com/v1"))
    recognition_ai_api_key: str | None = _stage_api_key(
        "RECOGNITION_AI_API_KEY", "RECOGNITION_AI_BASE_URL",
    )
    recognition_ai_schema_mode: str = os.getenv("RECOGNITION_AI_SCHEMA_MODE", os.getenv("AI_CHAT_SCHEMA_MODE", "json-schema"))
    recognition_model: str = os.getenv("RECOGNITION_MODEL", os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"))
    recognition_repair_model: str = os.getenv("RECOGNITION_REPAIR_MODEL", "qwen/qwen3.8-flash")
    recognition_repair_enabled: bool = os.getenv("RECOGNITION_REPAIR_ENABLED", "true").lower() in {"1", "true", "yes"}
    recognition_image_detail: str = os.getenv("RECOGNITION_IMAGE_DETAIL", os.getenv("OPENAI_VISION_DETAIL", "low"))
    recognition_image_max_dimension: int = int(os.getenv("RECOGNITION_IMAGE_MAX_DIMENSION", "0"))
    recognition_image_jpeg_quality: int = int(os.getenv("RECOGNITION_IMAGE_JPEG_QUALITY", "90"))
    outfit_generation_ai_provider: str = os.getenv("OUTFIT_GENERATION_AI_PROVIDER", os.getenv("AI_PROVIDER", "openai-compatible"))
    outfit_generation_ai_base_url: str = os.getenv("OUTFIT_GENERATION_AI_BASE_URL", os.getenv("AI_BASE_URL", "https://api.openai.com/v1"))
    outfit_generation_ai_api_key: str | None = _stage_api_key(
        "OUTFIT_GENERATION_AI_API_KEY", "OUTFIT_GENERATION_AI_BASE_URL",
    )
    outfit_generation_ai_schema_mode: str = os.getenv("OUTFIT_GENERATION_AI_SCHEMA_MODE", os.getenv("AI_CHAT_SCHEMA_MODE", "json-schema"))
    outfit_visual_ai_provider: str = os.getenv("OUTFIT_VISUAL_AI_PROVIDER", os.getenv("AI_PROVIDER", "openai-compatible"))
    outfit_visual_ai_base_url: str = os.getenv("OUTFIT_VISUAL_AI_BASE_URL", os.getenv("AI_BASE_URL", "https://api.openai.com/v1"))
    outfit_visual_ai_api_key: str | None = _stage_api_key(
        "OUTFIT_VISUAL_AI_API_KEY", "OUTFIT_VISUAL_AI_BASE_URL",
    )
    outfit_visual_ai_schema_mode: str = os.getenv("OUTFIT_VISUAL_AI_SCHEMA_MODE", os.getenv("AI_CHAT_SCHEMA_MODE", "json-schema"))
    openai_agent_planner_model: str = os.getenv("OPENAI_AGENT_PLANNER_MODEL", "gpt-4.1-mini")
    openai_embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    openai_embedding_dimensions: int = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))
    recognition_occasion_threshold: float = float(os.getenv("RECOGNITION_OCCASION_THRESHOLD", "0.8"))
    recognition_worker_batch_size: int = int(os.getenv("RECOGNITION_WORKER_BATCH_SIZE", "3"))
    recognition_worker_poll_seconds: float = float(os.getenv("RECOGNITION_WORKER_POLL_SECONDS", "2"))
    # Total provider attempts: the initial call plus three durable retries.
    recognition_worker_max_attempts: int = int(os.getenv("RECOGNITION_WORKER_MAX_ATTEMPTS", "4"))
    recognition_worker_job_timeout_seconds: int = int(os.getenv("RECOGNITION_WORKER_JOB_TIMEOUT_SECONDS", "120"))
    recognition_worker_retry_base_seconds: int = int(os.getenv("RECOGNITION_WORKER_RETRY_BASE_SECONDS", "10"))
    recognition_worker_retry_max_seconds: int = int(os.getenv("RECOGNITION_WORKER_RETRY_MAX_SECONDS", "300"))
    require_auth_for_mutations: bool = os.getenv("REQUIRE_AUTH_FOR_MUTATIONS", "true").lower() in {"1", "true", "yes"}
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    service_name: str = os.getenv("SERVICE_NAME", "ai-closet-api")
    observability_token: str | None = os.getenv("OBSERVABILITY_TOKEN") or None


settings = Settings()
