from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.constants import (
    DEFAULT_CATEGORY,
    DEFAULT_COLOR,
    DEFAULT_OCCASION,
    DEFAULT_RECOMMENDATION_LIMIT,
    DEFAULT_SEASON,
    DEFAULT_STYLE,
    DEFAULT_TEMPERATURE_F,
    RecognitionSource,
    RecognitionStatus,
)
from app.core.versions import CLOTHING_ANALYSIS_VERSION, FEATURE_SNAPSHOT_VERSION, ITEM_FEATURE_VERSION, TAXONOMY_VERSION


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClothingAnalysis(BaseModel):
    analysis_version: str = CLOTHING_ANALYSIS_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    category: str = DEFAULT_CATEGORY
    subtype: str | None = None
    color: str = DEFAULT_COLOR
    seasons: list[str] = Field(default_factory=lambda: [DEFAULT_SEASON])
    style: str = DEFAULT_STYLE
    occasion: str = DEFAULT_OCCASION
    material: str | None = None
    pattern: str | None = None
    fit: str | None = None
    length: str | None = None
    sleeve_length: str | None = None
    neckline: str | None = None
    layering_role: str | None = None
    warmth_level: int | None = None
    formality_score: int | None = None
    confidence: float | None = None
    summary: str | None = None
    source: str = RecognitionSource.HEURISTIC_FALLBACK
    raw_category: str | None = None
    raw_subtype: str | None = None
    raw_color: str | None = None
    raw_style: str | None = None
    raw_occasion: str | None = None
    raw_seasons: list[str] = Field(default_factory=list)


class ClothingItemRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    image_url: str
    image_path: str | None = None
    analysis_version: str = CLOTHING_ANALYSIS_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    feature_version: str = ITEM_FEATURE_VERSION
    recognition_status: str = RecognitionStatus.COMPLETE
    category: str
    subtype: str | None = None
    color: str = DEFAULT_COLOR
    season: str = DEFAULT_SEASON
    style: str = DEFAULT_STYLE
    occasion: str = DEFAULT_OCCASION
    material: str | None = None
    pattern: str | None = None
    fit: str | None = None
    length: str | None = None
    sleeve_length: str | None = None
    neckline: str | None = None
    layering_role: str | None = None
    warmth_level: int | None = None
    formality_score: int | None = None
    recognition_source: str | None = None
    recognition_summary: str | None = None
    recognition_confidence: float | None = None
    recognition_tags: dict[str, Any] | None = None
    feature_vector: list[float] | None = None
    semantic_vector: list[float] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class RecognitionRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    clothing_item_id: str
    provider: str
    model_name: str | None = None
    prompt_version: str | None = None
    analysis_version: str = CLOTHING_ANALYSIS_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    confidence: float | None = None
    category: str | None = None
    subtype: str | None = None
    color: str | None = None
    seasons: list[str] = Field(default_factory=list)
    style: str | None = None
    occasion: str | None = None
    material: str | None = None
    pattern: str | None = None
    fit: str | None = None
    length: str | None = None
    sleeve_length: str | None = None
    neckline: str | None = None
    layering_role: str | None = None
    warmth_level: int | None = None
    formality_score: int | None = None
    normalized_payload: dict[str, Any]
    raw_payload: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ItemFeatureSnapshot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    clothing_item_id: str
    feature_version: str = FEATURE_SNAPSHOT_VERSION
    feature_vector: list[float] | None = None
    extra_features: dict[str, Any] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class RecognitionJobRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    clothing_item_id: str
    filename: str
    image_url: str
    image_path: str | None = None
    status: str = RecognitionStatus.QUEUED
    attempts: int = 0
    last_error: str | None = None
    leased_at: str | None = None
    next_run_at: str | None = None
    dead_lettered_at: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class RecommendationContext(BaseModel):
    occasion: str = DEFAULT_OCCASION
    temperature_f: float = DEFAULT_TEMPERATURE_F
    preferred_style: str | None = None
    preferred_color: str | None = None
    limit: int = DEFAULT_RECOMMENDATION_LIMIT


class RecommendationBreakdown(BaseModel):
    semantic_fit: float = 0
    occasion_fit: float = 0
    weather_fit: float = 0
    style_harmony: float = 0
    color_harmony: float = 0
    category_balance: float = 0

    @property
    def total(self) -> float:
        return (
            self.semantic_fit
            + self.occasion_fit
            + self.weather_fit
            + self.style_harmony
            + self.color_harmony
            + self.category_balance
        )


class OutfitRecommendationRecord(BaseModel):
    id: str
    title: str = "Outfit candidate"
    score: float
    reasons: list[str]
    styling_notes: list[str] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    breakdown: RecommendationBreakdown
    items: list[ClothingItemRecord]


class SkillCallRecord(BaseModel):
    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
