from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, StrictBool, ConfigDict, model_validator

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


class OccasionScore(BaseModel):
    occasion: str
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class ColorTone(BaseModel):
    model_config = ConfigDict(extra='forbid')
    color: str
    hue: float | None = Field(default=None, ge=0, le=360, allow_inf_nan=False)
    saturation: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    lightness: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    evidence: str | None = None

    @field_validator('color')
    @classmethod
    def known_color(cls, value):
        from app.services.taxonomy import COLORS
        if value not in COLORS: raise ValueError('Color tone must use a canonical color tag')
        return value


class WearingProfile(BaseModel):
    """Garment capabilities, not the wearing mode selected for a particular outfit."""
    model_config = ConfigDict(extra='forbid')
    layering_region: Literal["upper_body", "lower_body", "full_body"] | None = None
    lower_layer_role: Literal["base", "outer"] | None = None
    can_wear_alone: StrictBool | None = None
    can_layer_over: StrictBool | None = None
    can_layer_under: StrictBool | None = None
    requires_inner_layer: StrictBool | None = None
    closure_type: Literal['pullover', 'buttons', 'zipper', 'open_front', 'wrap', 'other'] | None = None
    wearing_modes: list[Literal['standalone', 'inner_layer', 'outer_layer_closed', 'outer_layer_open']] = Field(default_factory=list)
    evidence: str | None = None

    @model_validator(mode='after')
    def consistent_capabilities(self):
        self.wearing_modes = list(dict.fromkeys(self.wearing_modes))
        if self.requires_inner_layer is True and (self.can_wear_alone is True or 'standalone' in self.wearing_modes):
            raise ValueError('A garment requiring an inner layer cannot be worn standalone')
        for capability, modes in [(self.can_wear_alone, ['standalone']),
                                   (self.can_layer_under, ['inner_layer']),
                                   (self.can_layer_over, ['outer_layer_closed','outer_layer_open'])]:
            if capability is False and any(mode in self.wearing_modes for mode in modes):
                raise ValueError('Wearing mode contradicts garment capability')
        if self.closure_type == 'pullover' and 'outer_layer_open' in self.wearing_modes:
            raise ValueError('A pullover cannot be worn open')
        return self


class ClothingAnalysis(BaseModel):
    color_tones: list[ColorTone] = Field(default_factory=list)
    wearing_profile: WearingProfile = Field(default_factory=WearingProfile)
    analysis_version: str = CLOTHING_ANALYSIS_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    category: str = DEFAULT_CATEGORY
    subtype: str | None = None
    color: str = DEFAULT_COLOR
    seasons: list[str] = Field(default_factory=lambda: DEFAULT_SEASON.split(", "))
    style: str = DEFAULT_STYLE
    occasion: str = DEFAULT_OCCASION
    occasion_scores: list[OccasionScore] = Field(default_factory=list)
    occasion_threshold: float | None = Field(default=None, ge=0, le=1)
    occasion_thresholds: dict[str, float] = Field(default_factory=dict)
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

    @field_validator('seasons', mode='before')
    @classmethod
    def four_seasons(cls, value):
        from app.services.season_support import normalize_user_seasons
        return normalize_user_seasons(value)


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

    @property
    def color_tones(self) -> list[dict]:
        tags = {v.strip() for v in self.color.split(',')}
        return [ColorTone.model_validate(t).model_dump() for t in (self.recognition_tags or {}).get('color_tones',[]) if t.get('color') in tags]

    @property
    def wearing_profile(self) -> dict:
        # Persisted inside recognition_tags; no duplicate SQL column or embedding.
        raw = (self.recognition_tags or {}).get('wearing_profile')
        return WearingProfile.model_validate(raw or {}).model_dump()


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


class ItemEditEvent(BaseModel):
    """An append-only record of a user-confirmed clothing-card correction."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    clothing_item_id: str
    edit_session_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    source: str = "unknown"
    changed_fields: list[str] = Field(default_factory=list)
    changes: dict[str, Any] = Field(default_factory=dict)
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
    outfit_id: str | None = None
    original_score: float | None = None
    wear_penalty: float = 0
    personalization_score: float = 0
    taste_profile_version: int | None = None
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
