from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.constants import DEFAULT_OCCASION, DEFAULT_RECOMMENDATION_LIMIT, DEFAULT_TEMPERATURE_F
from app.services.taxonomy import COLORS, OCCASIONS, STYLES


class IntentName:
    RECOMMEND = "recommend_outfits"
    SUMMARY = "closet_summary"
    ADVICE = "catalog_advice"


@dataclass(frozen=True)
class RecommendationIntentContext:
    occasion: str = DEFAULT_OCCASION
    preferred_style: str | None = None
    preferred_color: str | None = None
    temperature_f: float = DEFAULT_TEMPERATURE_F
    limit: int = DEFAULT_RECOMMENDATION_LIMIT
    trip_days: int | None = None


@dataclass(frozen=True)
class AgentIntent:
    primary_intent: str
    intents: tuple[str, ...]
    execution_order: tuple[str, ...]
    confidence: float
    recommendation: RecommendationIntentContext = field(default_factory=RecommendationIntentContext)
    reasoning_summary: str = ""
    raw_message: str = ""

    def as_metadata(self) -> dict:
        return {
            "primary_intent": self.primary_intent,
            "intents": list(self.intents),
            "execution_order": list(self.execution_order),
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "recommendation": {
                "occasion": self.recommendation.occasion,
                "preferred_style": self.recommendation.preferred_style,
                "preferred_color": self.recommendation.preferred_color,
                "temperature_f": self.recommendation.temperature_f,
                "limit": self.recommendation.limit,
                "trip_days": self.recommendation.trip_days,
            },
        }


def detect_agent_intent(message: str) -> AgentIntent:
    lowered = message.lower()
    recommendation_score = _keyword_score(
        lowered,
        ["recommend", "outfit", "wear", "look", "vacation", "trip", "搭配", "穿搭", "推荐", "度假", "looks"],
    )
    summary_score = _keyword_score(
        lowered,
        ["closet", "have", "inventory", "missing", "summary", "wardrobe", "衣柜", "有哪些", "缺", "总结"],
    )
    advice_score = _keyword_score(
        lowered,
        ["how", "why", "improve", "better", "advice", "help", "建议", "怎么", "为什么", "优化"],
    )

    scored_intents = [
        (IntentName.RECOMMEND, recommendation_score),
        (IntentName.SUMMARY, summary_score),
        (IntentName.ADVICE, advice_score),
    ]
    detected = tuple(name for name, score in scored_intents if score > 0)
    primary_intent = max(scored_intents, key=lambda item: item[1])[0]

    if not detected:
        detected = (IntentName.ADVICE,)
        primary_intent = IntentName.ADVICE

    total_score = sum(score for _, score in scored_intents)
    confidence = 0.55 if total_score == 0 else min(0.97, max(score for _, score in scored_intents) / total_score + 0.35)

    recommendation = RecommendationIntentContext(
        occasion=_extract_option(message, OCCASIONS, default=DEFAULT_OCCASION),
        preferred_style=_extract_option(message, STYLES, default=None),
        preferred_color=_extract_option(message, COLORS, default=None),
        temperature_f=_extract_temperature(message),
        limit=_extract_recommendation_limit(message),
        trip_days=_extract_trip_days(message),
    )
    execution_order = _normalize_execution_order(detected)
    return AgentIntent(
        primary_intent=primary_intent,
        intents=detected,
        execution_order=execution_order,
        confidence=confidence,
        recommendation=recommendation,
        reasoning_summary="Heuristic planner fallback based on detected wardrobe and recommendation keywords.",
        raw_message=message,
    )


def _keyword_score(lowered: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in lowered)


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


def _extract_trip_days(message: str) -> int | None:
    lowered = message.lower()
    for pattern in (
        r"(\d+)\s*(?:day|days)",
        r"(\d+)\s*天",
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
        if re.search(rf"\b{re.escape(token)}\b\s*(?:day|days)", lowered):
            return _bounded_limit(value)
        if f"{token}天" in message:
            return _bounded_limit(value)
    return None


def _extract_recommendation_limit(message: str) -> int:
    lowered = message.lower()
    for pattern in (
        r"(\d+)\s*(?:day|days|look|looks|outfit|outfits)",
        r"(\d+)\s*(?:套|天)",
    ):
        if match := re.search(pattern, lowered):
            return _bounded_limit(int(match.group(1)))

    trip_days = _extract_trip_days(message)
    if trip_days is not None:
        return trip_days

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
        if re.search(rf"\b{re.escape(token)}\b\s*(?:look|looks|outfit|outfits)", lowered):
            return _bounded_limit(value)
        if f"{token}套" in message:
            return _bounded_limit(value)

    return DEFAULT_RECOMMENDATION_LIMIT


def _bounded_limit(value: int) -> int:
    return max(1, min(value, 10))


def _normalize_execution_order(intents: tuple[str, ...]) -> tuple[str, ...]:
    preferred_order = (
        IntentName.RECOMMEND,
        IntentName.SUMMARY,
        IntentName.ADVICE,
    )
    ordered = [intent for intent in preferred_order if intent in intents]
    return tuple(ordered or (IntentName.ADVICE,))
