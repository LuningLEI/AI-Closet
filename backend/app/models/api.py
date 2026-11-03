from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.constants import SIGNED_IMAGE_URL_EXPIRES_SECONDS
from app.core.versions import PROFILE_VERSION, STYLE_PREFERENCE_VERSION, TAXONOMY_VERSION
from app.models.domain import ClothingItemRecord, OutfitRecommendationRecord, RecommendationContext, SkillCallRecord


class ClosetSummaryResponse(BaseModel):
    total_items: int
    category_counts: dict[str, int]
    recent_items: list[ClothingItemRecord]


class BatchUploadFailure(BaseModel):
    filename: str
    detail: str


class UploadQueueStatus(BaseModel):
    clothing_item_id: str
    recognition_status: str
    image_path: str | None = None


class BatchUploadResponse(BaseModel):
    items: list[ClothingItemRecord]
    errors: list[BatchUploadFailure] = Field(default_factory=list)
    queued: list[UploadQueueStatus] = Field(default_factory=list)


class SignedUrlContract(BaseModel):
    expires_in_seconds: int = SIGNED_IMAGE_URL_EXPIRES_SECONDS
    refresh_strategy: str = "Call the owning API again to receive a fresh signed image URL."


class ClothingItemUpdateRequest(BaseModel):
    category: str
    subtype: str | None = None
    color: str
    season: str
    style: str
    occasion: str
    recognition_summary: str | None = None
    material: str | None = None
    length: str | None = None
    sleeve_length: str | None = None
    edit_source: Literal["ios", "unknown", "ios_card_open"] = "unknown"
    occasion_before: str | None = None
    occasion_threshold_at_edit: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    occasion_thresholds_at_edit: dict[str, float] | None = None

    @field_validator('material', 'length', 'sleeve_length', mode='before')
    @classmethod
    def clean_details(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @model_validator(mode='before')
    @classmethod
    def canonical_catalog(cls, data):
        from app.services.catalog_support import canonical_pair, canonical_occasions
        data = dict(data)
        data['category'],data['subtype'] = canonical_pair(data.get('category'),data.get('subtype'))
        for key in ['occasion','occasion_before']:
            if data.get(key) is not None:data[key]=canonical_occasions(data[key])
        return data

    @field_validator('season', mode='before')
    @classmethod
    def four_seasons(cls, value):
        from app.services.season_support import normalize_user_seasons
        return ', '.join(normalize_user_seasons(value))

    @field_validator('occasion_thresholds_at_edit', mode='before')
    @classmethod
    def validate_occasion_thresholds(cls, value):
        if value is None:
            return None
        import math
        if not isinstance(value,dict) or not value:raise ValueError('Occasion thresholds must be a non-empty object.')
        result={}
        for label,threshold in value.items():
            if not isinstance(label,str) or not label.strip() or len(label.strip())>60:
                raise ValueError('Invalid occasion label.')
            if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<=threshold<=1:
                raise ValueError('Occasion thresholds must be between zero and one.')
            result[label.strip()]=float(threshold)
        return result


class ImageEditMetadata(BaseModel):
    rotation_quarter_turns: int = Field(ge=0, le=3)
    zoom_scale: float = Field(ge=1, le=8)
    drag_x: float
    drag_y: float
    editor_side: float = Field(gt=0)


class RecommendationsRequest(RecommendationContext):
    # Ephemeral client-page seed. It changes presentation among near-tied
    # results without becoming part of the durable recommendation context.
    rotation_seed: str | None = Field(default=None, min_length=1, max_length=64)


class RecommendationsResponse(BaseModel):
    context: RecommendationContext
    recommendations: list[OutfitRecommendationRecord]


class WeatherLocationResponse(BaseModel):
    label: str
    detail: str
    latitude: float
    longitude: float
    source: str


class WeatherResponse(BaseModel):
    temperature_f: float
    feels_like_f: float
    precipitation: float | None = None
    wind_mph: float | None = None
    condition: str
    weather_code: int | None = None
    source: str


class TodayRecommendationResponse(BaseModel):
    location: WeatherLocationResponse
    weather: WeatherResponse
    context: RecommendationContext
    recommendations: list[OutfitRecommendationRecord]


class TodayWeatherResponse(BaseModel):
    location: WeatherLocationResponse
    weather: WeatherResponse


class UserPreferencesResponse(BaseModel):
    user_id: str
    profile_version: str = PROFILE_VERSION
    taxonomy_version: str = TAXONOMY_VERSION
    style_preference_version: str = STYLE_PREFERENCE_VERSION
    onboarding_completed: bool = False
    nickname: str | None = None
    avatar_path: str | None = None
    avatar_url: str | None = None
    birth_year: int | None = None
    gender_identity: str | None = None
    daily_occasions: list[str] = Field(default_factory=list)
    style_preferences: list[str] = Field(default_factory=list)
    occasion_style_preferences: dict[str, list[str]] = Field(default_factory=dict)
    selected_categories: list[str] = Field(default_factory=list)
    custom_categories: list[str] = Field(default_factory=list)
    taxonomy_customizations: dict[str, Any] = Field(default_factory=dict)
    model_training_consent: bool = False
    personalization_enabled: bool = True
    feedback_learning_enabled: bool = True
    exploration_level: Literal["familiar", "balanced", "adventurous"] = "balanced"
    rotation_level: Literal["repeat_freely", "balanced", "more_variety"] = "balanced"
    temperature_sensitivity: Literal["runs_cold", "neutral", "runs_warm"] = "neutral"
    profile_features: dict[str, Any] = Field(default_factory=dict)
    default_location_label: str | None = None
    default_latitude: float | None = None
    default_longitude: float | None = None
    temperature_unit: str = "F"
    preferences: dict[str, Any] = Field(default_factory=dict)


class UserPreferencesUpdateRequest(BaseModel):
    profile_version: str | None = None
    taxonomy_version: str | None = None
    style_preference_version: str | None = None
    onboarding_completed: bool | None = None
    nickname: str | None = None
    avatar_path: str | None = None
    birth_year: int | None = None
    gender_identity: str | None = None
    daily_occasions: list[str] | None = None
    style_preferences: list[str] | None = None
    occasion_style_preferences: dict[str, list[str]] | None = None
    selected_categories: list[str] | None = None
    custom_categories: list[str] | None = None
    taxonomy_customizations: dict[str, Any] | None = None
    model_training_consent: bool | None = None
    personalization_enabled: bool | None = None
    feedback_learning_enabled: bool | None = None
    exploration_level: Literal["familiar", "balanced", "adventurous"] | None = None
    rotation_level: Literal["repeat_freely", "balanced", "more_variety"] | None = None
    temperature_sensitivity: Literal["runs_cold", "neutral", "runs_warm"] | None = None
    profile_features: dict[str, Any] | None = None
    default_location_label: str | None = None
    default_latitude: float | None = None
    default_longitude: float | None = None
    temperature_unit: str | None = None
    preferences: dict[str, Any] | None = None

    @field_validator('preferences')
    @classmethod
    def validate_preference_thresholds(cls, value):
        if value is not None and 'occasion_thresholds' in value:
            from app.services.occasion_thresholds import validate_thresholds
            validate_thresholds(value['occasion_thresholds'])
        return value


class QueueErrorSummary(BaseModel):
    id: str
    filename: str
    attempts: int
    last_error: str | None = None


class QueueHealthResponse(BaseModel):
    total_jobs: int
    status_counts: dict[str, int]
    oldest_queued_at: str | None = None
    processing_jobs: int
    dead_letter_jobs: int
    recent_errors: list[QueueErrorSummary] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    reply: str
    metadata: dict[str, Any] | None = None
    skills_used: list[SkillCallRecord] = Field(default_factory=list)


class TaxonomyResponse(BaseModel):
    categories: list[str]
    colors: list[str]
    styles: list[str]
    occasions: list[str]
    seasons: list[str]
    subtypes: dict[str, list[str]]
    lengths: list[str]
    sleeve_lengths: list[str]
