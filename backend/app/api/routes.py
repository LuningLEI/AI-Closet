from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, status

from app.core.constants import API_V1_PREFIX, DEFAULT_OCCASION, DEFAULT_USER_ID, MAX_BATCH_UPLOADS, TODAY_RECOMMENDATION_LIMIT
from app.core.config import settings
from app.agent.runtime import WardrobeAgentRuntime
from app.models.api import (
    BatchUploadFailure,
    BatchUploadResponse,
    ChatRequest,
    ChatResponse,
    ClothingItemUpdateRequest,
    ClosetSummaryResponse,
    RecommendationsRequest,
    RecommendationsResponse,
    QueueHealthResponse,
    SignedUrlContract,
    TaxonomyResponse,
    TodayRecommendationResponse,
    TodayWeatherResponse,
    UploadQueueStatus,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
)
from app.models.domain import ClothingItemRecord, OutfitRecommendationRecord, RecommendationContext
from app.repositories.factory import build_closet_repository
from app.services.embedding_service import EmbeddingService
from app.services.auth_service import AuthService
from app.services.item_service import ItemService
from app.services.profile_service import ProfileService
from app.services.recommendation import RecommendationEngine
from app.services.response_signing import ResponseSigningService
from app.services.storage_service import StorageService
from app.services.taxonomy import CATEGORIES, COLORS, OCCASIONS, SEASONS, STYLES, SUBTYPES, merge_preferences, user_categories, user_subtypes
from app.services.upload_service import UploadService
from app.services.weather_service import WeatherService

router = APIRouter(prefix=API_V1_PREFIX)

repository = build_closet_repository()
storage_service = StorageService()
recommendation_engine = RecommendationEngine()
embedding_service = EmbeddingService()
weather_service = WeatherService()
auth_service = AuthService()
agent_runtime = WardrobeAgentRuntime(repository, recommendation_engine)
signing_service = ResponseSigningService(storage_service)
profile_service = ProfileService(repository, storage_service)
upload_service = UploadService(repository, storage_service)
item_service = ItemService(repository, embedding_service, storage_service)


def current_user_id(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        authenticated_user_id = auth_service.user_id_from_token(token)
        if authenticated_user_id:
            return authenticated_user_id
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase auth token.")

    if settings.supabase_url:
        raise HTTPException(status_code=401, detail="Login required.")

    return request.headers.get("x-ai-closet-user-id") or DEFAULT_USER_ID


def mutation_user_id(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        authenticated_user_id = auth_service.user_id_from_token(token)
        if authenticated_user_id:
            return authenticated_user_id
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase auth token.")

    if settings.require_auth_for_mutations or settings.supabase_url:
        raise HTTPException(status_code=401, detail="Login required for write operations.")

    return request.headers.get("x-ai-closet-user-id") or DEFAULT_USER_ID


def signed_item(item: ClothingItemRecord, request: Request) -> ClothingItemRecord:
    return signing_service.item(item, str(request.base_url))


def signed_items(items: list[ClothingItemRecord], request: Request) -> list[ClothingItemRecord]:
    return signing_service.items(items, str(request.base_url))


def signed_recommendations(recommendations, request: Request):
    return signing_service.recommendations(recommendations, str(request.base_url))


def signed_preferences(preferences: dict, request: Request) -> dict:
    return signing_service.preferences(preferences, str(request.base_url))


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/storage/signed-url-contract", response_model=SignedUrlContract)
def signed_url_contract() -> SignedUrlContract:
    return SignedUrlContract()


@router.get("/admin/queue/health", response_model=QueueHealthResponse)
def queue_health(request: Request) -> QueueHealthResponse:
    return QueueHealthResponse.model_validate(repository.queue_health(current_user_id(request)))


@router.get("/taxonomy", response_model=TaxonomyResponse)
def taxonomy(request: Request) -> TaxonomyResponse:
    categories = CATEGORIES
    subtypes = SUBTYPES
    try:
        user_id = current_user_id(request)
        preferences = merge_preferences(repository.get_preferences(user_id).get("preferences", {}))
        categories = user_categories(preferences)
        subtypes = user_subtypes(categories)
    except HTTPException:
        if settings.supabase_url:
            raise
    return TaxonomyResponse(
        categories=categories,
        colors=COLORS,
        styles=STYLES,
        occasions=OCCASIONS,
        seasons=SEASONS,
        subtypes=subtypes,
    )


@router.get("/items", response_model=list[ClothingItemRecord])
def list_items(request: Request) -> list[ClothingItemRecord]:
    return signed_items(repository.list_items(current_user_id(request)), request)


@router.get("/summary", response_model=ClosetSummaryResponse)
def closet_summary(request: Request) -> ClosetSummaryResponse:
    summary = repository.summary(current_user_id(request))
    summary["recent_items"] = signed_items(summary["recent_items"], request)
    return ClosetSummaryResponse.model_validate(summary)


@router.get("/preferences", response_model=UserPreferencesResponse)
def get_preferences(request: Request) -> UserPreferencesResponse:
    return UserPreferencesResponse.model_validate(signed_preferences(repository.get_preferences(current_user_id(request)), request))


@router.patch("/preferences", response_model=UserPreferencesResponse)
def update_preferences(request: Request, payload: UserPreferencesUpdateRequest) -> UserPreferencesResponse:
    user_id = mutation_user_id(request)
    updates = payload.model_dump(exclude_unset=True)
    return UserPreferencesResponse.model_validate(signed_preferences(repository.upsert_preferences(user_id, updates), request))


@router.post("/profile/avatar", response_model=UserPreferencesResponse)
async def upload_profile_avatar(request: Request, file: UploadFile = File(...)) -> UserPreferencesResponse:
    user_id = mutation_user_id(request)
    preferences = await profile_service.upload_avatar(user_id, file)
    return UserPreferencesResponse.model_validate(signed_preferences(preferences, request))


@router.get("/today/recommendation", response_model=TodayRecommendationResponse)
def today_recommendation(
    request: Request,
    latitude: float | None = None,
    longitude: float | None = None,
    location: str | None = None,
    location_label: str | None = None,
) -> TodayRecommendationResponse:
    user_id = current_user_id(request)
    try:
        today_context = weather_service.get_today_context(latitude, longitude, location, location_label)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    weather = today_context["weather"]
    context = RecommendationContext(
        occasion=DEFAULT_OCCASION,
        temperature_f=float(weather["feels_like_f"]),
        preferred_style=None,
        preferred_color=None,
        limit=TODAY_RECOMMENDATION_LIMIT,
    )
    preferences = repository.get_preferences(user_id).get("preferences", {})
    recommendations = signed_recommendations(
        recommendation_engine.recommend(repository.list_items_for_recommendation(user_id), context, preferences),
        request,
    )
    return TodayRecommendationResponse(
        location=today_context["location"],
        weather=weather,
        context=context,
        recommendations=recommendations,
    )


@router.get("/today/weather", response_model=TodayWeatherResponse)
def today_weather(
    latitude: float | None = None,
    longitude: float | None = None,
    location: str | None = None,
    location_label: str | None = None,
) -> TodayWeatherResponse:
    try:
        today_context = weather_service.get_today_context(latitude, longitude, location, location_label)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return TodayWeatherResponse(
        location=today_context["location"],
        weather=today_context["weather"],
    )


@router.patch("/items/{item_id}", response_model=ClothingItemRecord)
def update_item(request: Request, item_id: str, payload: ClothingItemUpdateRequest) -> ClothingItemRecord:
    user_id = mutation_user_id(request)
    updated_item = item_service.update_item(user_id, item_id, payload)
    return signed_item(updated_item, request)


@router.post("/items/{item_id}/image", response_model=ClothingItemRecord)
async def replace_item_image(
    request: Request,
    item_id: str,
    file: UploadFile = File(...),
) -> ClothingItemRecord:
    user_id = mutation_user_id(request)
    print(
        "[routes.replace_item_image]",
        {
            "item_id": item_id,
            "user_id": user_id,
            "filename": file.filename,
            "content_type": file.content_type,
        },
    )
    updated_item = await item_service.replace_item_image(user_id, item_id, file, str(request.base_url))
    return signed_item(updated_item, request)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(request: Request, item_id: str) -> Response:
    user_id = mutation_user_id(request)
    print("[routes.delete_item]", {"item_id": item_id, "user_id": user_id})
    item_service.delete_item(user_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/items/upload", response_model=ClothingItemRecord)
async def upload_item(
    request: Request,
    file: UploadFile = File(...),
) -> ClothingItemRecord:
    return await _queue_uploaded_item(request, file)


@router.post("/items/upload-batch", response_model=BatchUploadResponse)
async def upload_items(
    request: Request,
    files: list[UploadFile] = File(...),
) -> BatchUploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one image is required.")
    if len(files) > MAX_BATCH_UPLOADS:
        raise HTTPException(status_code=400, detail=f"Upload at most {MAX_BATCH_UPLOADS} images at a time.")

    items: list[ClothingItemRecord] = []
    errors: list[BatchUploadFailure] = []

    for file in files:
        try:
            items.append(await _queue_uploaded_item(request, file))
        except Exception as error:
            errors.append(BatchUploadFailure(filename=file.filename or "upload.jpg", detail=str(error)))

    if not items and errors:
        raise HTTPException(status_code=400, detail={"message": "No files were uploaded.", "errors": [error.model_dump() for error in errors]})

    return BatchUploadResponse(
        items=items,
        errors=errors,
        queued=[
            UploadQueueStatus(
                clothing_item_id=item.id,
                recognition_status=item.recognition_status,
                image_path=item.image_path,
            )
            for item in items
        ],
    )


async def _queue_uploaded_item(
    request: Request,
    file: UploadFile,
) -> ClothingItemRecord:
    user_id = mutation_user_id(request)
    saved_item = await upload_service.queue_clothing_item(user_id, file, str(request.base_url))
    return signed_item(saved_item, request)


@router.post("/recommendations", response_model=RecommendationsResponse)
def recommendations(request: Request, payload: RecommendationsRequest) -> RecommendationsResponse:
    user_id = current_user_id(request)
    preferences = repository.get_preferences(user_id).get("preferences", {})
    recommendations = signed_recommendations(
        recommendation_engine.recommend(
            repository.list_items_for_recommendation(user_id),
            payload,
            preferences,
        ),
        request,
    )
    return RecommendationsResponse(context=payload, recommendations=recommendations)


@router.post("/chat", response_model=ChatResponse)
def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    response = agent_runtime.respond(payload.message, current_user_id(request))
    metadata = dict(response.metadata or {})
    raw_recommendations = metadata.get("recommendations")
    if isinstance(raw_recommendations, list) and raw_recommendations:
        recommendations = [OutfitRecommendationRecord.model_validate(item) for item in raw_recommendations]
        metadata["recommendations"] = [item.model_dump() for item in signed_recommendations(recommendations, request)]
        return response.model_copy(update={"metadata": metadata})
    return response
