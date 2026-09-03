from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.agent.intents import AgentIntent
from app.core.constants import DEFAULT_CATEGORY, DEFAULT_OCCASION, DEFAULT_RECOMMENDATION_LIMIT, DEFAULT_TEMPERATURE_F
from app.models.domain import ClothingItemRecord, RecommendationContext, SkillCallRecord
from app.repositories.closet_repository import ClosetRepository
from app.services.recommendation import RecommendationEngine
from app.services.taxonomy import COLORS, OCCASIONS, STYLES, merge_preferences, user_categories


@dataclass
class SkillResult:
    summary: str
    payload: dict


class Skill(Protocol):
    name: str
    description: str

    def run(self, message: str, user_id: str | None = None, intent: AgentIntent | None = None) -> SkillResult:
        ...


class ClosetSummarySkill:
    name = "closet_summary"
    description = "Summarize current closet coverage and identify missing categories."

    def __init__(self, repository: ClosetRepository) -> None:
        self.repository = repository

    def run(self, message: str, user_id: str | None = None, intent: AgentIntent | None = None) -> SkillResult:
        summary = self.repository.summary(user_id)
        preferences = self.repository.get_preferences(user_id).get("preferences", {}) if user_id else {}
        core_categories = [category for category in user_categories(merge_preferences(preferences)) if category != DEFAULT_CATEGORY]
        missing = [category for category in core_categories[:5] if summary["category_counts"].get(category, 0) == 0]
        reply = f"You have {summary['total_items']} items tracked."
        if missing:
            reply += f" The biggest gaps are {', '.join(missing)}."
        else:
            reply += " Core outfit categories are covered."
        return SkillResult(summary=reply, payload={"summary": summary, "missing_categories": missing})


class RecommendationSkill:
    name = "recommend_outfits"
    description = "Generate outfit recommendations from the current closet and context."

    def __init__(self, repository: ClosetRepository, engine: RecommendationEngine) -> None:
        self.repository = repository
        self.engine = engine

    def run(self, message: str, user_id: str | None = None, intent: AgentIntent | None = None) -> SkillResult:
        recommendation_intent = intent.recommendation if intent else None
        requested_limit = recommendation_intent.limit if recommendation_intent else _extract_recommendation_limit(message)
        context = RecommendationContext(
            occasion=recommendation_intent.occasion if recommendation_intent else _extract_option(message, OCCASIONS, default=DEFAULT_OCCASION),
            preferred_style=recommendation_intent.preferred_style if recommendation_intent else _extract_option(message, STYLES, default=None),
            preferred_color=recommendation_intent.preferred_color if recommendation_intent else _extract_option(message, COLORS, default=None),
            temperature_f=recommendation_intent.temperature_f if recommendation_intent else _extract_temperature(message),
            limit=requested_limit,
        )
        preferences = self.repository.get_preferences(user_id).get("preferences", {}) if user_id else {}
        recommendations = self.engine.recommend(self.repository.list_items_for_recommendation(user_id), context, preferences)
        if not recommendations:
            return SkillResult(
                summary="I could not form a strong outfit yet. Add more tops, bottoms, or shoes, or loosen the occasion and season constraints.",
                payload={"context": context.model_dump(), "recommendations": []},
            )

        reply = _recommendation_strategy_summary(
            context,
            recommendations,
            requested_limit,
            trip_days=recommendation_intent.trip_days if recommendation_intent else None,
        )
        return SkillResult(
            summary=reply,
            payload={"context": context.model_dump(), "recommendations": [item.model_dump() for item in recommendations]},
        )


class CatalogAdviceSkill:
    name = "catalog_advice"
    description = "Explain how metadata and agent skills fit together for this closet."

    def __init__(self, repository: ClosetRepository) -> None:
        self.repository = repository

    def run(self, message: str, user_id: str | None = None, intent: AgentIntent | None = None) -> SkillResult:
        total = len(self.repository.list_items(user_id))
        reply = (
            "The system stores each item with structured metadata, then exposes that state to skills for summary, recommendation, and chat flows. "
            f"Right now there are {total} indexed items available to the agent layer."
        )
        return SkillResult(summary=reply, payload={"total_items": total})


def build_skill_call(name: str, payload: dict) -> SkillCallRecord:
    return SkillCallRecord(name=name, output=payload)


def _extract_option(message: str, options: list[str], default: str | None) -> str | None:
    lowered = message.lower()
    for option in options:
        if option.lower() in lowered:
            return option
    return default


def _extract_temperature(message: str) -> float:
    for token in message.replace("°", " ").split():
        normalized = token.rstrip("fF")
        if normalized.isdigit():
            return float(normalized)
    return DEFAULT_TEMPERATURE_F


def _extract_recommendation_limit(message: str) -> int:
    lowered = message.lower()
    for pattern in (
        r"(\d+)\s*(?:day|days|look|looks|outfit|outfits)",
        r"(\d+)\s*(?:套|天)",
    ):
        if match := re.search(pattern, lowered):
            return _bounded_limit(int(match.group(1)))

    word_to_number = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    for token, value in word_to_number.items():
        if re.search(rf"\b{re.escape(token)}\b\s*(?:day|days|look|looks|outfit|outfits)", lowered):
            return _bounded_limit(value)
        if f"{token}天" in message or f"{token}套" in message:
            return _bounded_limit(value)

    return DEFAULT_RECOMMENDATION_LIMIT


def _bounded_limit(value: int) -> int:
    return max(1, min(value, 10))


def _recommendation_strategy_summary(
    context: RecommendationContext,
    recommendations,
    requested_limit: int,
    trip_days: int | None = None,
) -> str:
    actual_limit = len(recommendations)
    light_layer_count = sum(1 for recommendation in recommendations if any(item.category == "Outerwear" for item in recommendation.items))
    full_body_count = sum(
        1
        for recommendation in recommendations
        if any(item.category in {"Dresses", "Jumpsuits", "Sets", "Swimwear"} for item in recommendation.items)
    )
    shoe_supported_count = sum(1 for recommendation in recommendations if any(item.category == "Shoes" for item in recommendation.items))

    lines = [
        f"I planned {actual_limit} look{'s' if actual_limit != 1 else ''} for this request."
    ]

    if trip_days and actual_limit < trip_days:
        lines.append("I returned the strongest distinct looks available from the current closet, even though the closet does not yet support a fully unique look for every requested day.")

    if requested_limit > 1:
        lines.append("The mix is meant to feel varied across the trip instead of repeating the same silhouette every day.")

    if context.temperature_f >= 75:
        lines.append("The overall direction stays light and breathable for warm weather.")
    elif context.temperature_f <= 55:
        lines.append("The overall direction keeps warmth and layering in mind for cooler weather.")
    else:
        lines.append("The overall direction balances comfort, layering, and easy day-to-night wear.")

    if full_body_count >= max(1, actual_limit // 2):
        lines.append("Several looks lean on one-piece dressing or full-body silhouettes to keep packing simple.")
    else:
        lines.append("The looks lean on separates so you can remix pieces across multiple days.")

    if light_layer_count > 0:
        lines.append("Light layers are included where they help with evening plans or colder indoor spaces.")

    if shoe_supported_count == actual_limit and actual_limit > 0:
        lines.append("Each look is grounded with a full outfit structure so it can be worn without extra guesswork.")

    return " ".join(lines)
