from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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


class RecommendationsRequest(RecommendationContext):
    pass


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
    selected_categories: list[str] = Field(default_factory=list)
    custom_categories: list[str] = Field(default_factory=list)
    model_training_consent: bool = False
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
    selected_categories: list[str] | None = None
    custom_categories: list[str] | None = None
    model_training_consent: bool | None = None
    profile_features: dict[str, Any] | None = None
    default_location_label: str | None = None
    default_latitude: float | None = None
    default_longitude: float | None = None
    temperature_unit: str | None = None
    preferences: dict[str, Any] | None = None


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
