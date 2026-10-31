"""Single preference-aware ranking use case for Today and Recommendations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.domain import OutfitRecommendationRecord, RecommendationContext
from app.outfits.recommendations import recommend_library
from app.services.recommendation.engine import RecommendationEngine


@dataclass(frozen=True)
class RecommendationRequestSource:
    name: str
    initial_context: dict[str, Any]


class PersonalizedRecommendationService:
    """Ranks the same saved outfit pool with the same preference/taste policy.

    Source-specific code may derive the initial context (weather for Today,
    explicit filters for Recommendations), but cannot select another algorithm.
    """

    algorithm_version = "personalized-library-ranking-v1"

    def __init__(self, repository, engine: RecommendationEngine) -> None:
        self.repository = repository
        self.engine = engine

    def rank(self, user_id: str, context: RecommendationContext,
             *, source: RecommendationRequestSource) -> list[OutfitRecommendationRecord]:
        preferences = self.repository.get_preferences(user_id).get("preferences", {})
        return recommend_library(self.repository, self.engine, user_id, context, preferences)
