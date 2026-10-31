from fastapi import APIRouter, HTTPException, Request

from app.api import dependencies as deps
from app.core.constants import DEFAULT_OCCASION, TODAY_RECOMMENDATION_LIMIT
from app.models.api import (ChatRequest, ChatResponse, RecommendationsRequest,
                            RecommendationsResponse, TodayRecommendationResponse,
                            TodayWeatherResponse)
from app.models.domain import OutfitRecommendationRecord, RecommendationContext
from app.services.recommendation.application import RecommendationRequestSource

router = APIRouter()


def signed_recommendations(recommendations, request: Request):
    return deps.signing_service.recommendations(recommendations, str(request.base_url))


@router.get("/today/recommendation", response_model=TodayRecommendationResponse)
def today_recommendation(request: Request, latitude: float | None = None,
                         longitude: float | None = None, location: str | None = None,
                         location_label: str | None = None) -> TodayRecommendationResponse:
    user_id = deps.current_user_id(request)
    try:
        today = deps.weather_service.get_today_context(latitude, longitude, location, location_label)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    weather = today["weather"]
    context = RecommendationContext(occasion=DEFAULT_OCCASION,
                                    temperature_f=float(weather["feels_like_f"]),
                                    limit=TODAY_RECOMMENDATION_LIMIT)
    ranked = deps.recommendation_service.rank(user_id, context, source=RecommendationRequestSource(
        name="today", initial_context={"weather_source": weather.get("source")}))
    return TodayRecommendationResponse(location=today["location"], weather=weather, context=context,
                                       recommendations=signed_recommendations(ranked, request))


@router.get("/today/weather", response_model=TodayWeatherResponse)
def today_weather(latitude: float | None = None, longitude: float | None = None,
                  location: str | None = None, location_label: str | None = None) -> TodayWeatherResponse:
    try:
        today = deps.weather_service.get_today_context(latitude, longitude, location, location_label)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return TodayWeatherResponse(location=today["location"], weather=today["weather"])


@router.post("/recommendations", response_model=RecommendationsResponse)
def recommendations(request: Request, payload: RecommendationsRequest) -> RecommendationsResponse:
    user_id = deps.current_user_id(request)
    ranked = deps.recommendation_service.rank(user_id, payload, source=RecommendationRequestSource(
        name="recommendations", initial_context=payload.model_dump()))
    return RecommendationsResponse(context=payload, recommendations=signed_recommendations(ranked, request))


@router.post("/chat", response_model=ChatResponse)
def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    response = deps.agent_runtime.respond(payload.message, deps.current_user_id(request))
    metadata = dict(response.metadata or {})
    raw = metadata.get("recommendations")
    if isinstance(raw, list) and raw:
        records = [OutfitRecommendationRecord.model_validate(item) for item in raw]
        metadata["recommendations"] = [item.model_dump() for item in signed_recommendations(records, request)]
        return response.model_copy(update={"metadata": metadata})
    return response
