from fastapi import APIRouter, File, Request, UploadFile

from app.api import dependencies as deps
from app.models.api import UserPreferencesResponse, UserPreferencesUpdateRequest

router = APIRouter()


def signed_preferences(preferences: dict, request: Request) -> dict:
    return deps.signing_service.preferences(preferences, str(request.base_url))


@router.get("/preferences", response_model=UserPreferencesResponse)
def get_preferences(request: Request) -> UserPreferencesResponse:
    result = deps.repository.get_preferences(deps.current_user_id(request))
    return UserPreferencesResponse.model_validate(signed_preferences(result, request))


@router.patch("/preferences", response_model=UserPreferencesResponse)
def update_preferences(request: Request, payload: UserPreferencesUpdateRequest) -> UserPreferencesResponse:
    result = deps.repository.upsert_preferences(deps.mutation_user_id(request), payload.model_dump(exclude_unset=True))
    return UserPreferencesResponse.model_validate(signed_preferences(result, request))


@router.post("/profile/avatar", response_model=UserPreferencesResponse)
async def upload_profile_avatar(request: Request, file: UploadFile = File(...)) -> UserPreferencesResponse:
    result = await deps.profile_service.upload_avatar(deps.mutation_user_id(request), file)
    return UserPreferencesResponse.model_validate(signed_preferences(result, request))
