from __future__ import annotations

from app.core.constants import (
    RECOMMENDATION_MAX_CANDIDATES,
    RECOMMENDATION_OPTIONAL_SHORTLIST_LIMIT,
    RECOMMENDATION_OPTIONAL_SLOT_LIMIT,
    RECOMMENDATION_PRIMARY_SHORTLIST_LIMIT,
    RECOMMENDATION_PRIMARY_SLOT_LIMIT,
    RECOGNITION_EXCLUDED_SOURCES,
    SPARSE_PRIMARY_LIMIT,
    SPARSE_SECONDARY_LIMIT,
)
from app.models.domain import ClothingItemRecord, RecommendationContext
from app.services.recommendation.models import Candidate
from app.services.recommendation.rules import item_occasion_tokens, recommendation_slot, tights_layering_valid
from app.services.taxonomy import merge_preferences, preferred_styles_for_occasion, user_categories
from app.services.layering_fit import assess_layering_pair


class CandidateGenerator:
    def filter_recognized_items(
        self,
        items: list[ClothingItemRecord],
        user_preferences: dict | None = None,
    ) -> list[ClothingItemRecord]:
        preferences = merge_preferences(user_preferences)
        allowed_categories = set(user_categories(preferences))
        return [
            item
            for item in items
            if item.recognition_source not in RECOGNITION_EXCLUDED_SOURCES and item.category in allowed_categories
        ]

    def generate(
        self,
        items: list[ClothingItemRecord],
        context: RecommendationContext,
        user_preferences: dict | None = None,
    ) -> list[Candidate]:
        grouped = self.group_by_category(items, context, user_preferences)
        candidates = self._generate_candidates(grouped, context)
        complete_candidates = [candidate for candidate in candidates if candidate.is_complete_outfit]
        if complete_candidates:
            return complete_candidates

        structured_candidates = [candidate for candidate in candidates if candidate.has_core_outfit]
        if structured_candidates:
            return structured_candidates

        return candidates

    def group_by_category(
        self,
        items: list[ClothingItemRecord],
        context: RecommendationContext,
        user_preferences: dict | None = None,
    ) -> dict[str, list[ClothingItemRecord]]:
        grouped: dict[str, list[ClothingItemRecord]] = {}
        for item in items:
            grouped.setdefault(recommendation_slot(item.category, item.subtype), []).append(item)

        for slot, slot_items in list(grouped.items()):
            grouped[slot] = self._shortlist_items(slot_items, slot, context, user_preferences)
        return grouped

    def _generate_candidates(
        self,
        grouped: dict[str, list[ClothingItemRecord]],
        context: RecommendationContext,
    ) -> list[Candidate]:
        tops = grouped.get("Tops", [])[:RECOMMENDATION_PRIMARY_SLOT_LIMIT]
        bottoms = grouped.get("Bottoms", [])[:RECOMMENDATION_PRIMARY_SLOT_LIMIT]
        full_body_items = grouped.get("FullBody", [])[:RECOMMENDATION_PRIMARY_SLOT_LIMIT]

        shoe_options = [None] + grouped.get("Shoes", [])[:RECOMMENDATION_OPTIONAL_SLOT_LIMIT]
        accessory_options = [None] + grouped.get("Accessories", [])[:RECOMMENDATION_OPTIONAL_SLOT_LIMIT]

        seen: set[str] = set()
        results: list[Candidate] = []

        for full_body in full_body_items:
            outerwear_options = self._outerwear_options([full_body], grouped.get("Outerwear", []))
            for shoes in shoe_options:
                for outerwear in outerwear_options:
                    for accessory in accessory_options:
                            self._append_unique(
                                results,
                                seen,
                                Candidate(full_body=full_body, shoes=shoes, outerwear=outerwear, accessory=accessory),
                            )
                            if len(results) >= RECOMMENDATION_MAX_CANDIDATES:
                                return results

        for top in tops:
            for bottom in bottoms:
                outerwear_options = self._outerwear_options([top], grouped.get("Outerwear", []))
                for shoes in shoe_options:
                    for outerwear in outerwear_options:
                        for accessory in accessory_options:
                            self._append_unique(
                                results,
                                seen,
                                Candidate(
                                    top=top,
                                    bottom=bottom,
                                    shoes=shoes,
                                    outerwear=outerwear,
                                    accessory=accessory,
                                ),
                            )
                            if len(results) >= RECOMMENDATION_MAX_CANDIDATES:
                                return results

        # Sparse-closet fallbacks keep the page useful before users have complete outfit coverage.
        for item in full_body_items[:SPARSE_PRIMARY_LIMIT]:
            self._append_unique(results, seen, Candidate(full_body=item))

        for item in tops[:SPARSE_PRIMARY_LIMIT]:
            self._append_unique(results, seen, Candidate(top=item))

        for item in bottoms[:SPARSE_PRIMARY_LIMIT]:
            self._append_unique(results, seen, Candidate(bottom=item))

        for item in grouped.get("Outerwear", [])[:SPARSE_SECONDARY_LIMIT]:
            self._append_unique(results, seen, Candidate(outerwear=item))

        for item in grouped.get("Shoes", [])[:SPARSE_SECONDARY_LIMIT]:
            self._append_unique(results, seen, Candidate(shoes=item))

        for item in grouped.get("Accessories", [])[:SPARSE_SECONDARY_LIMIT]:
            self._append_unique(results, seen, Candidate(accessory=item))
            if len(results) >= RECOMMENDATION_MAX_CANDIDATES:
                return results
        return results

    def _outerwear_options(
        self,
        inners: list[ClothingItemRecord],
        outerwear: list[ClothingItemRecord],
    ) -> list[ClothingItemRecord | None]:
        ranked = []
        for position, outer in enumerate(outerwear):
            assessments = [assess_layering_pair(inner, outer) for inner in inners]
            if assessments and any(assessment.hard_failure for assessment in assessments):
                continue
            score = min((assessment.score for assessment in assessments), default=0.0)
            ranked.append((score, position, outer))
        ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2].id))
        return [None] + [entry[2] for entry in ranked[:RECOMMENDATION_OPTIONAL_SLOT_LIMIT]]

    def _shortlist_items(
        self,
        items: list[ClothingItemRecord],
        slot: str,
        context: RecommendationContext,
        user_preferences: dict | None = None,
    ) -> list[ClothingItemRecord]:
        shortlisted = sorted(
            items,
            key=lambda item: (
                -self._item_relevance_score(item, slot, context, user_preferences),
                item.created_at,
                item.id,
            ),
        )
        limit = (
            RECOMMENDATION_PRIMARY_SLOT_LIMIT
            if slot == "Outerwear"
            else RECOMMENDATION_OPTIONAL_SHORTLIST_LIMIT
            if slot in {"Shoes", "Accessories"}
            else RECOMMENDATION_PRIMARY_SHORTLIST_LIMIT
        )
        return shortlisted[:limit]

    def _item_relevance_score(
        self,
        item: ClothingItemRecord,
        slot: str,
        context: RecommendationContext,
        user_preferences: dict | None = None,
    ) -> float:
        score = 0.0
        score += self._occasion_score(item, context.occasion)
        score += self._temperature_score(item, slot, context.temperature_f)
        score += self._style_score(item, context, user_preferences)
        score += self._color_score(item, context.preferred_color)
        score += self._recognition_quality_score(item)
        return score

    def _occasion_score(self, item: ClothingItemRecord, occasion: str) -> float:
        item_occasions = item_occasion_tokens(item)
        requested = occasion.lower()
        if requested == "everyday":
            return 30 if item_occasions.intersection({"everyday", "work", "travel", "school"}) else 18
        if requested in item_occasions:
            return 34
        if "everyday" in item_occasions:
            return 22
        if requested in {"party", "date", "wedding", "evening"} and item_occasions.intersection({"party", "date", "wedding", "evening"}):
            return 24
        if requested in {"work", "business"} and item_occasions.intersection({"work", "business", "everyday"}):
            return 24
        return 10

    def _temperature_score(self, item: ClothingItemRecord, slot: str, temperature_f: float) -> float:
        seasons = {token.strip().lower().replace(" ", "-") for token in item.season.split(",")}
        warmth = item.warmth_level or 3
        score = 0.0

        if temperature_f < 45:
            score += 18 if warmth >= 4 else 10
            if slot in {"Outerwear", "Tops"}:
                score += 8
        elif temperature_f < 65:
            score += 18 if 2 <= warmth <= 4 else 10
            if slot == "Outerwear":
                score += 6
        elif temperature_f < 78:
            score += 18 if warmth <= 3 else 10
        else:
            score += 20 if warmth <= 2 else 8
            if slot == "Outerwear":
                score -= 8

        if "all-season" in seasons:
            score += 6
        elif temperature_f < 65 and seasons.intersection({"winter", "fall"}):
            score += 6
        elif temperature_f >= 65 and seasons.intersection({"spring", "summer"}):
            score += 6
        return score

    def _style_score(
        self,
        item: ClothingItemRecord,
        context: RecommendationContext,
        user_preferences: dict | None = None,
    ) -> float:
        preferred_style = context.preferred_style
        preferred_styles = [preferred_style] if preferred_style else preferred_styles_for_occasion(user_preferences, context.occasion)

        if not preferred_styles:
            return 12
        if item.style.lower() in {style.lower() for style in preferred_styles}:
            return 18
        return 10

    def _color_score(self, item: ClothingItemRecord, preferred_color: str | None) -> float:
        if not preferred_color:
            return 6
        if preferred_color.lower() in {color.strip().lower() for color in item.color.split(",")}:
            return 12
        return 4

    def _recognition_quality_score(self, item: ClothingItemRecord) -> float:
        confidence = item.recognition_confidence or 0
        quality = confidence * 10
        if item.semantic_vector:
            quality += 4
        if item.subtype:
            quality += 2
        return quality

    def _append_unique(self, results: list[Candidate], seen: set[str], candidate: Candidate) -> None:
        if not tights_layering_valid(candidate.items):
            return
        if candidate.identifier not in seen:
            seen.add(candidate.identifier)
            results.append(candidate)
