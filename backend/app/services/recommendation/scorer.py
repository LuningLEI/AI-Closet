from __future__ import annotations

from math import sqrt

from app.core.constants import (
    ACCEPTABLE_SEMANTIC_SCORE,
    COLD_WEATHER_F,
    COOL_WEATHER_F,
    FLEXIBLE_OCCASION_SCORE,
    LAYERING_MAX_WEATHER_F,
    MAX_COLOR_SCORE,
    MAX_COMPLETENESS_SCORE,
    MAX_SEMANTIC_SCORE,
    MAX_STYLE_SCORE,
    MIN_RECOMMENDATION_SCORE,
    NEUTRAL_COLORS,
    STRONG_OCCASION_SCORE,
    STRONG_SEMANTIC_SCORE,
)
from app.models.domain import ClothingItemRecord, OutfitRecommendationRecord, RecommendationBreakdown, RecommendationContext
from app.services.embedding_service import EmbeddingService
from app.services.recommendation.models import Candidate
from app.services.recommendation.rules import allowed_seasons, item_occasion_tokens, tights_layering_valid
from app.services.taxonomy import preferred_styles_for_occasion
from app.services.taste_profile import outfit_taste_score
from app.services.personalization_settings import effective_temperature_f, resolve_personalization_settings
from app.services.layering_fit import assess_outfit_layering


class CandidateScorer:
    def __init__(self, embedding_service: EmbeddingService) -> None:
        self.embedding_service = embedding_service

    def score(
        self,
        candidate: Candidate,
        context: RecommendationContext,
        context_vector: list[float] | None,
        preferences: dict | None = None,
        *,
        trusted_user_outfit: bool = False,
        prevalidated_library_outfit: bool = False,
        taste_profile: dict | None = None,
    ) -> OutfitRecommendationRecord | None:
        if not trusted_user_outfit and not tights_layering_valid(candidate.items):
            return None
        breakdown = RecommendationBreakdown()
        reasons: list[str] = []
        styling_notes: list[str] = []

        breakdown.semantic_fit, semantic_reason = self._semantic_score(candidate, context_vector)
        reasons.append(semantic_reason)

        breakdown.occasion_fit, occasion_reason = self._occasion_score(candidate, context)
        reasons.append(occasion_reason)

        settings = resolve_personalization_settings(preferences)
        styling_temperature = effective_temperature_f(context.temperature_f, settings)
        styling_context = context.model_copy(update={"temperature_f": styling_temperature})
        breakdown.weather_fit, weather_reason = self._weather_score(candidate, styling_temperature)
        reasons.append(weather_reason)

        style_preferences = (
            [context.preferred_style]
            if context.preferred_style
            else preferred_styles_for_occasion(preferences, context.occasion)
            if settings.personalization_enabled
            else []
        )
        breakdown.style_harmony, style_reason = self._style_score(candidate, style_preferences)
        reasons.append(style_reason)

        breakdown.color_harmony, color_reason = self._color_score(candidate)
        reasons.append(color_reason)
        if context.preferred_color:
            color_bonus, color_preference_reason = self._preferred_color_bonus(candidate, context.preferred_color)
            breakdown.color_harmony = min(MAX_COLOR_SCORE, breakdown.color_harmony + color_bonus)
            if color_preference_reason:
                reasons.append(color_preference_reason)

        breakdown.category_balance, missing_slots = self._completeness_score(candidate, styling_context)
        if missing_slots:
            styling_notes.append(f"Could improve with: {', '.join(missing_slots)}.")
        else:
            reasons.append("Builds a complete outfit instead of isolated pieces.")

        layering = assess_outfit_layering(candidate.items)
        if layering:
            if layering.hard_failure and not trusted_user_outfit:
                return None
            breakdown.layering_fit = -layering.penalty
            if layering.penalty:
                reasons.append("Layering room is limited: " + "; ".join(layering.reasons[:2]) + ".")

        # A saved generated outfit has already passed structural rules and visual
        # review.  Today's occasion and temperature should change its rank, not
        # erase it from the reusable library-backed recommendation pool.
        if (
            not trusted_user_outfit
            and not prevalidated_library_outfit
            and breakdown.total <= MIN_RECOMMENDATION_SCORE
        ):
            return None

        personalization = (
            outfit_taste_score(candidate.items, taste_profile, {"occasion": context.occasion})
            if settings.personalization_enabled and settings.feedback_learning_enabled
            else 0.0
        )
        if personalization:
            reasons.append("Adjusted using your learned outfit preferences.")
        return OutfitRecommendationRecord(
            id=candidate.identifier,
            title=self._title(candidate),
            score=round(max(0, breakdown.total + personalization), 2),
            personalization_score=round(personalization, 2),
            taste_profile_version=(taste_profile or {}).get("profile_version"),
            reasons=reasons[:3],
            styling_notes=styling_notes or self._styling_notes(candidate, styling_context),
            missing_slots=missing_slots,
            breakdown=breakdown,
            items=candidate.items,
        )

    def _semantic_score(self, candidate: Candidate, context_vector: list[float] | None) -> tuple[float, str]:
        outfit_vector = self._outfit_vector(candidate)
        if not context_vector or not outfit_vector:
            return 0, "ML semantic fit is unavailable until embeddings are generated."

        similarity = max(0.0, self._cosine_similarity(context_vector, outfit_vector))
        score = min(MAX_SEMANTIC_SCORE, similarity * MAX_SEMANTIC_SCORE)
        if score >= STRONG_SEMANTIC_SCORE:
            return score, "ML semantic fit strongly matches the outfit request."
        if score >= ACCEPTABLE_SEMANTIC_SCORE:
            return score, "ML semantic fit supports this outfit for the request."
        return score, "ML semantic fit is acceptable, with other styling constraints carrying the recommendation."

    def _outfit_vector(self, candidate: Candidate) -> list[float] | None:
        vectors = [self._item_vector(item) for item in candidate.items]
        usable_vectors = [vector for vector in vectors if vector]
        if not usable_vectors:
            return None
        dimension = len(usable_vectors[0])
        averaged = []
        for index in range(dimension):
            averaged.append(sum(vector[index] for vector in usable_vectors if len(vector) == dimension) / len(usable_vectors))
        return averaged

    def _item_vector(self, item: ClothingItemRecord) -> list[float] | None:
        return item.semantic_vector

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sqrt(sum(a * a for a in left))
        right_norm = sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0
        return dot / (left_norm * right_norm)

    def _occasion_score(self, candidate: Candidate, context: RecommendationContext) -> tuple[float, str]:
        requested = context.occasion.lower()
        scores = []
        for item in candidate.items:
            item_occasions = item_occasion_tokens(item)
            if requested == "everyday":
                scores.append(18 if item_occasions.intersection({"everyday", "travel", "work"}) else 12)
            elif requested in item_occasions:
                scores.append(25)
            elif "everyday" in item_occasions:
                scores.append(16)
            elif requested in {"party", "date", "wedding", "evening"} and item_occasions.intersection({"party", "date", "wedding", "evening"}):
                scores.append(19)
            elif requested in {"work", "business"} and item_occasions.intersection({"work", "everyday"}):
                scores.append(18)
            else:
                scores.append(8)
        score = sum(scores) / len(scores)
        if score >= STRONG_OCCASION_SCORE:
            return score, f"Strong fit for a {context.occasion.lower()} setting."
        if score >= FLEXIBLE_OCCASION_SCORE:
            return score, f"Works for {context.occasion.lower()} with a flexible styling read."
        return score, f"Occasion fit is softer, but the pieces can be adapted for {context.occasion.lower()}."

    def _weather_score(self, candidate: Candidate, temperature_f: float) -> tuple[float, str]:
        has_outerwear = candidate.outerwear is not None
        season_score = self._season_alignment_score(candidate, temperature_f)
        layering_penalty = self._outerwear_balance_penalty(candidate, temperature_f)
        if temperature_f < COLD_WEATHER_F:
            base = 20 if has_outerwear else 8
            return (
                max(0, (base + season_score) / 2 - layering_penalty),
                "Uses outerwear for colder weather." if has_outerwear else "Could use an extra layer in the cold.",
            )
        if temperature_f < COOL_WEATHER_F:
            base = 20 if has_outerwear else 15
            return (max(0, (base + season_score) / 2 - layering_penalty), "Balanced for mild temperatures with optional outerwear.")
        if temperature_f < LAYERING_MAX_WEATHER_F:
            base = 14 if has_outerwear else 20
            return (
                max(0, (base + season_score) / 2 - layering_penalty),
                "Outerwear adds coverage for cooler indoor spaces." if has_outerwear else "Light enough for moderate weather.",
            )
        base = 5 if has_outerwear else 21
        return (
            max(0, (base + season_score) / 2 - layering_penalty),
            "A bit layered for warmer weather." if has_outerwear else "Keeps things light for warm weather.",
        )

    def _season_alignment_score(self, candidate: Candidate, temperature_f: float) -> float:
        allowed = allowed_seasons(temperature_f)
        item_scores = []
        for item in candidate.items:
            item_seasons = {token.strip().lower().replace(" ", "-") for token in item.season.split(",")}
            if "all-season" in item_seasons:
                item_scores.append(18)
            elif item_seasons.intersection(allowed):
                item_scores.append(20)
            else:
                item_scores.append(8)
        return sum(item_scores) / len(item_scores)

    def _style_score(self, candidate: Candidate, preferred_styles: list[str]) -> tuple[float, str]:
        styles = [item.style.strip().lower() for item in candidate.items]
        dominant = max(set(styles), key=styles.count)
        preferred = {style.strip().lower() for style in preferred_styles if style.strip()}
        score = styles.count(dominant) * 4
        if dominant in preferred:
            score += 10
        elif preferred.intersection(styles):
            score += 6
        score = min(score + 6, MAX_STYLE_SCORE)
        matched = next((style for style in preferred_styles if style.strip().lower() in styles), None)
        reason = (
            f"Includes your {matched.lower()} style preference."
            if matched
            else "Keeps the outfit visually consistent."
            if dominant == "casual"
            else f"Leans into a {dominant} styling direction."
        )
        return score, reason

    def _color_score(self, candidate: Candidate) -> tuple[float, str]:
        colors = [color.strip().lower() for item in candidate.items for color in item.color.split(",") if color.strip()]
        unique = set(colors)
        neutral_count = sum(1 for color in colors if color in NEUTRAL_COLORS)
        accent_count = len([color for color in unique if color not in NEUTRAL_COLORS and color != "unknown"])

        if len(unique) <= 2:
            return 22, "Tight color palette helps the look feel polished."
        if accent_count >= 3:
            return 6, "Too many competing accent colors make the outfit feel less cohesive."
        if accent_count >= 2 and neutral_count == 0:
            return 8, "Multiple statement colors compete instead of working together."
        if neutral_count >= 2:
            return 18, "Neutral pieces keep the colors under control."
        if len(unique) == len(colors):
            return 10, "More color variety makes the look bolder."
        return 14, "Color mix stays reasonably coordinated."

    def _preferred_color_bonus(self, candidate: Candidate, preferred_color: str) -> tuple[float, str | None]:
        if any(preferred_color.lower() in {color.strip().lower() for color in item.color.split(",")} for item in candidate.items):
            return 3, f"Includes your {preferred_color.lower()} color preference."
        return 0, None

    def _completeness_score(self, candidate: Candidate, context: RecommendationContext) -> tuple[float, list[str]]:
        missing: list[str] = []
        has_any_top = candidate.top is not None
        if candidate.full_body:
            base = 14
        elif has_any_top and candidate.bottom:
            base = 13
        else:
            base = 8
            if not has_any_top and not candidate.full_body:
                missing.append("top or dress")
            if not candidate.bottom and not candidate.full_body:
                missing.append("bottom")
            if has_any_top and not candidate.bottom:
                missing.append("bottom")
            if candidate.bottom and not has_any_top:
                missing.append("top")

        if context.temperature_f < COOL_WEATHER_F and not candidate.outerwear:
            missing.append("outerwear")

        if candidate.shoes:
            base += 4
        else:
            missing.append("shoes")
        if context.temperature_f < COOL_WEATHER_F and not candidate.outerwear:
            missing.append("outerwear")
        elif candidate.outerwear:
            base += 2
        if candidate.accessory:
            base += 2
        return min(base, MAX_COMPLETENESS_SCORE), list(dict.fromkeys(missing))

    def _title(self, candidate: Candidate) -> str:
        lead = candidate.full_body or candidate.top or candidate.bottom
        if not lead:
            return "Outfit candidate"
        descriptor = lead.subtype or lead.category
        return f"{lead.color} {descriptor}"

    def _styling_notes(self, candidate: Candidate, context: RecommendationContext) -> list[str]:
        notes: list[str] = []
        if candidate.top and candidate.outerwear:
            layer_names = [
                item.subtype or item.category
                for item in [candidate.top, candidate.outerwear]
            ]
            notes.append(f"Layer in this order: {' under '.join(layer_names)}.")
        if candidate.outerwear and context.temperature_f >= LAYERING_MAX_WEATHER_F:
            notes.append("Keep the outerwear optional for warmer moments.")
        if candidate.accessory:
            notes.append("Use the accessory as the finishing detail rather than the focal point.")
        if not notes:
            notes.append("Wear as a clean base outfit; adjust accessories by setting.")
        return notes

    def _outerwear_balance_penalty(self, candidate: Candidate, temperature_f: float) -> float:
        outerwear = candidate.outerwear
        anchor = candidate.full_body or candidate.top
        if not outerwear or not anchor:
            return 0

        anchor_warmth = self._estimated_warmth(anchor)
        outerwear_warmth = self._estimated_warmth(outerwear)
        warmth_gap = outerwear_warmth - anchor_warmth

        if temperature_f >= LAYERING_MAX_WEATHER_F and outerwear_warmth >= 4:
            return 8
        if anchor.category in {"Dresses", "Swimwear"} and warmth_gap >= 2 and temperature_f >= COOL_WEATHER_F:
            return 7
        if warmth_gap >= 3:
            return 6
        return 0

    def _estimated_warmth(self, item: ClothingItemRecord) -> int:
        if item.warmth_level is not None:
            return item.warmth_level

        descriptor = f"{item.category} {item.subtype or ''} {item.recognition_summary or ''}".lower()
        if any(token in descriptor for token in ["puffer", "parka", "wool coat", "down", "fleece", "heavy"]):
            return 5
        if any(token in descriptor for token in ["coat", "jacket", "hoodie", "sweater", "cardigan", "blazer"]):
            return 4
        if any(token in descriptor for token in ["dress", "skirt", "tank", "camisole", "tee", "t-shirt", "shorts", "slip"]):
            return 1
        if any(token in descriptor for token in ["shirt", "blouse", "trousers", "jeans"]):
            return 2
        return 3
