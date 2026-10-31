"""Application-scoped services shared by API route modules."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.agent.runtime import WardrobeAgentRuntime
from app.core.config import settings
from app.core.constants import DEFAULT_USER_ID
from app.repositories.factory import build_closet_repository
from app.services.auth_service import AuthService
from app.services.embedding_service import EmbeddingService
from app.services.item_service import ItemService
from app.services.profile_service import ProfileService
from app.services.recommendation import RecommendationEngine
from app.services.recommendation.application import PersonalizedRecommendationService
from app.services.response_signing import ResponseSigningService
from app.services.storage_service import StorageService
from app.services.upload_service import UploadService
from app.services.weather_service import WeatherService

repository = build_closet_repository()
storage_service = StorageService()
recommendation_engine = RecommendationEngine()
recommendation_service = PersonalizedRecommendationService(repository, recommendation_engine)
embedding_service = EmbeddingService()
weather_service = WeatherService()
auth_service = AuthService()
agent_runtime = WardrobeAgentRuntime(repository, recommendation_engine)
signing_service = ResponseSigningService(storage_service, repository)
profile_service = ProfileService(repository, storage_service)
upload_service = UploadService(repository, storage_service)
item_service = ItemService(repository, embedding_service, storage_service)


def current_user_id(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        user_id = auth_service.user_id_from_token(token)
        if user_id:
            return user_id
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase auth token.")
    if settings.supabase_url:
        raise HTTPException(status_code=401, detail="Login required.")
    return request.headers.get("x-ai-closet-user-id") or DEFAULT_USER_ID


def mutation_user_id(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        user_id = auth_service.user_id_from_token(token)
        if user_id:
            return user_id
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase auth token.")
    if settings.require_auth_for_mutations or settings.supabase_url:
        raise HTTPException(status_code=401, detail="Login required for write operations.")
    return request.headers.get("x-ai-closet-user-id") or DEFAULT_USER_ID
