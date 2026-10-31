import secrets

from fastapi import APIRouter, HTTPException, Request

from app.api import dependencies as deps
from app.core.runtime_snapshot import runtime_config_snapshot
from app.core.config import settings
from app.core.observability import metrics_snapshot
from app.models.api import QueueHealthResponse, SignedUrlContract, TaxonomyResponse
from app.services.taxonomy import (CATEGORIES, COLORS, LENGTHS, OCCASIONS, SEASONS,
                                   SLEEVE_LENGTHS, STYLES, SUBTYPES, merge_preferences,
                                   user_taxonomy)

router = APIRouter()


@router.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness() -> dict[str, str]:
    return {"status": "ready", "config_hash": runtime_config_snapshot().config_hash}


@router.get("/admin/metrics")
def metrics(request: Request) -> dict[str, int]:
    supplied = request.headers.get("x-observability-token", "")
    if not settings.observability_token or not secrets.compare_digest(supplied, settings.observability_token):
        raise HTTPException(status_code=404, detail="Not found")
    return metrics_snapshot()


@router.get("/storage/signed-url-contract", response_model=SignedUrlContract)
def signed_url_contract() -> SignedUrlContract:
    return SignedUrlContract()


@router.get("/admin/queue/health", response_model=QueueHealthResponse)
def queue_health(request: Request) -> QueueHealthResponse:
    return QueueHealthResponse.model_validate(deps.repository.queue_health(deps.current_user_id(request)))


@router.get("/taxonomy", response_model=TaxonomyResponse)
def taxonomy(request: Request) -> TaxonomyResponse:
    fallback = {"categories": CATEGORIES, "subtypes": SUBTYPES, "colors": COLORS, "styles": STYLES,
                "occasions": OCCASIONS, "seasons": SEASONS, "lengths": LENGTHS,
                "sleeve_lengths": SLEEVE_LENGTHS}
    user_id = deps.current_user_id(request)
    preferences = merge_preferences(deps.repository.get_preferences(user_id).get("preferences", {}))
    return TaxonomyResponse(**(user_taxonomy(preferences) or fallback))
