"""Immutable, hashable configuration identity attached to production work."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.versions import (
    CLOTHING_ANALYSIS_VERSION,
    ITEM_FEATURE_VERSION,
    STYLE_PREFERENCE_VERSION,
    TAXONOMY_PROMPT_VERSION,
    TAXONOMY_VERSION,
)
from app.outfits.config import digest
from app.services.taste_profile import ALGORITHM_VERSION, DEFAULT_TASTE_LEARNING_CONFIG


class RuntimeConfigSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: str = "runtime-config-snapshot-v1"
    created_at: str
    environment: str
    ai_provider: str
    taxonomy_version: str
    taxonomy_prompt_version: str
    recognition_version: str
    feature_version: str
    style_preference_version: str
    taste_algorithm_version: str
    taste_parameters: dict[str, Any]
    outfit_generation_key: str | None = None
    outfit_evaluator_key: str | None = None
    config_hash: str


def runtime_config_snapshot(outfit_config=None) -> RuntimeConfigSnapshot:
    values: dict[str, Any] = {
        "schema_version": "runtime-config-snapshot-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": settings.app_env,
        "ai_provider": settings.ai_provider,
        "taxonomy_version": TAXONOMY_VERSION,
        "taxonomy_prompt_version": TAXONOMY_PROMPT_VERSION,
        "recognition_version": CLOTHING_ANALYSIS_VERSION,
        "feature_version": ITEM_FEATURE_VERSION,
        "style_preference_version": STYLE_PREFERENCE_VERSION,
        "taste_algorithm_version": ALGORITHM_VERSION,
        "taste_parameters": DEFAULT_TASTE_LEARNING_CONFIG.__dict__,
        "outfit_generation_key": getattr(outfit_config, "generation_key", None),
        "outfit_evaluator_key": getattr(outfit_config, "evaluator_key", None),
    }
    identity = {key: value for key, value in values.items() if key != "created_at"}
    values["config_hash"] = digest(identity)
    return RuntimeConfigSnapshot.model_validate(values)
