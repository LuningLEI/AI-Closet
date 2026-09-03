from __future__ import annotations

from app.models.domain import ClothingItemRecord, OutfitRecommendationRecord, RecommendationContext
from app.services.embedding_service import EmbeddingService, recommendation_context_text
from app.services.recommendation.candidates import CandidateGenerator
from app.services.recommendation.scorer import CandidateScorer
from app.services.recommendation.rules import profile_memory_text
from app.services.taxonomy import merge_preferences


class RecommendationEngine:
    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        candidate_generator: CandidateGenerator | None = None,
        scorer: CandidateScorer | None = None,
    ) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.candidate_generator = candidate_generator or CandidateGenerator()
        self.scorer = scorer or CandidateScorer(self.embedding_service)

    def recommend(
        self,
        items: list[ClothingItemRecord],
        context: RecommendationContext,
        user_preferences: dict | None = None,
    ) -> list[OutfitRecommendationRecord]:
        preferences = merge_preferences(user_preferences)
        recognized_items = self.candidate_generator.filter_recognized_items(items, preferences)
        candidates = self.candidate_generator.generate(recognized_items, context, preferences)
        has_semantic_vectors = any(item.semantic_vector for item in recognized_items)
        context_vector = None
        if has_semantic_vectors:
            context_vector = self.embedding_service.create_embedding(
                recommendation_context_text(context) + " " + profile_memory_text(preferences)
            )

        recommendations = [
            recommendation
            for candidate in candidates
            if (recommendation := self.scorer.score(candidate, context, context_vector, preferences))
        ]
        recommendations.sort(key=lambda item: (-item.score, item.id))
        recommendations = self._prefer_structured_outfits(recommendations)
        recommendations = self._diversify(recommendations, context.limit)
        return recommendations[: context.limit]

    def _prefer_structured_outfits(
        self,
        recommendations: list[OutfitRecommendationRecord],
    ) -> list[OutfitRecommendationRecord]:
        complete = [recommendation for recommendation in recommendations if self._is_complete_outfit(recommendation)]
        if complete:
            return complete

        structured = [recommendation for recommendation in recommendations if self._has_core_outfit(recommendation)]
        if structured:
            return structured

        return recommendations

    def _diversify(
        self,
        recommendations: list[OutfitRecommendationRecord],
        limit: int,
    ) -> list[OutfitRecommendationRecord]:
        primary: list[OutfitRecommendationRecord] = []
        seen_signatures: set[str] = set()
        seen_leads: set[str] = set()

        for recommendation in recommendations:
            signature = self._structure_signature(recommendation)
            lead_id = self._lead_item_id(recommendation)
            if signature in seen_signatures:
                continue
            if lead_id and lead_id in seen_leads:
                continue
            primary.append(recommendation)
            seen_signatures.add(signature)
            if lead_id:
                seen_leads.add(lead_id)
            if len(primary) >= limit:
                return primary

        if len(primary) >= limit:
            return primary

        for recommendation in recommendations:
            signature = self._structure_signature(recommendation)
            if signature in seen_signatures:
                continue
            primary.append(recommendation)
            seen_signatures.add(signature)
            if len(primary) >= limit:
                break
        return primary

    def _has_core_outfit(self, recommendation: OutfitRecommendationRecord) -> bool:
        categories = [item.category for item in recommendation.items]
        has_full_body = any(category in {"Dresses", "Jumpsuits", "Sets", "Swimwear"} for category in categories)
        has_top = "Tops" in categories or "Activewear" in categories or "Intimates" in categories
        has_bottom = "Bottoms" in categories
        return has_full_body or (has_top and has_bottom)

    def _is_complete_outfit(self, recommendation: OutfitRecommendationRecord) -> bool:
        categories = [item.category for item in recommendation.items]
        return self._has_core_outfit(recommendation) and "Shoes" in categories

    def _lead_item_id(self, recommendation: OutfitRecommendationRecord) -> str | None:
        ordered_categories = ("Dresses", "Jumpsuits", "Sets", "Swimwear", "Tops", "Bottoms", "Shoes")
        for category in ordered_categories:
            for item in recommendation.items:
                if item.category == category:
                    return item.id
        return recommendation.items[0].id if recommendation.items else None

    def _structure_signature(self, recommendation: OutfitRecommendationRecord) -> str:
        grouped: dict[str, list[str]] = {}
        for item in recommendation.items:
            grouped.setdefault(item.category, []).append(item.id)

        parts: list[str] = []
        for category in sorted(grouped):
            parts.append(f"{category}:{','.join(sorted(grouped[category]))}")
        return "|".join(parts)
