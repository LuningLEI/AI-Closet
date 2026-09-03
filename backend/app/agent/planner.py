from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.agent.intents import (
    AgentIntent,
    IntentName,
    RecommendationIntentContext,
    detect_agent_intent,
)
from app.core.config import settings
from app.core.constants import OPENAI_RESPONSES_URL, OPENAI_RESPONSES_TIMEOUT_SECONDS


class AgentPlanner:
    def plan(self, message: str) -> AgentIntent:
        if settings.openai_api_key:
            try:
                return self._plan_with_openai(message)
            except Exception as error:
                print("AGENT PLANNER FALLBACK:", error)
        return detect_agent_intent(message)

    def _plan_with_openai(self, message: str) -> AgentIntent:
        response = httpx.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_agent_planner_model,
                "input": [
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": self._planner_prompt(),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": message,
                            }
                        ],
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "wardrobe_agent_plan",
                        "schema": self._planner_schema(),
                        "strict": True,
                    }
                },
            },
            timeout=OPENAI_RESPONSES_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        parsed = self._parse_response_json(payload)
        return self._intent_from_model_output(parsed, message)

    def _planner_prompt(self) -> str:
        return (
            "You are the planning layer for an AI wardrobe assistant. "
            "Classify the user request, decide which internal skills should run, and extract structured recommendation context. "
            "Available skills are: recommend_outfits, closet_summary, catalog_advice. "
            "Use recommend_outfits for styling requests, trip packing looks, outfit generation, or what-to-wear questions. "
            "Use closet_summary for questions about what the user owns, missing categories, or wardrobe coverage. "
            "Use catalog_advice for general advice, strategy, explanation, or fallback guidance. "
            "Return a strict JSON object only. "
            "If the user asks for multiple days or multiple looks, set both recommendation.limit and recommendation.trip_days appropriately. "
            "Keep reasoning_summary concise and high-level."
        )

    def _planner_schema(self) -> dict[str, Any]:
        intent_values = [IntentName.RECOMMEND, IntentName.SUMMARY, IntentName.ADVICE]
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "primary_intent": {"type": "string", "enum": intent_values},
                "intents": {
                    "type": "array",
                    "items": {"type": "string", "enum": intent_values},
                    "minItems": 1,
                    "maxItems": 3,
                    "uniqueItems": True,
                },
                "execution_order": {
                    "type": "array",
                    "items": {"type": "string", "enum": intent_values},
                    "minItems": 1,
                    "maxItems": 3,
                    "uniqueItems": True,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "reasoning_summary": {"type": "string"},
                "recommendation": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "occasion": {"type": "string"},
                        "preferred_style": {"type": ["string", "null"]},
                        "preferred_color": {"type": ["string", "null"]},
                        "temperature_f": {"type": "number"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                        "trip_days": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    },
                    "required": [
                        "occasion",
                        "preferred_style",
                        "preferred_color",
                        "temperature_f",
                        "limit",
                        "trip_days",
                    ],
                },
            },
            "required": [
                "primary_intent",
                "intents",
                "execution_order",
                "confidence",
                "reasoning_summary",
                "recommendation",
            ],
        }

    def _parse_response_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("output_text")
        if not text:
            chunks: list[str] = []
            for output_item in payload.get("output", []):
                for content_item in output_item.get("content", []):
                    if content_item.get("type") in {"output_text", "text"} and content_item.get("text"):
                        chunks.append(content_item["text"])
            text = "\n".join(chunks)

        if not text:
            raise ValueError("Planner response did not include output text.")

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        return json.loads(cleaned)

    def _intent_from_model_output(self, parsed: dict[str, Any], message: str) -> AgentIntent:
        fallback = detect_agent_intent(message)
        recommendation = parsed.get("recommendation") or {}
        intents = self._normalize_intent_list(parsed.get("intents"), fallback.intents)
        execution_order = self._normalize_execution_order(parsed.get("execution_order"), intents, fallback.execution_order)
        primary_intent = parsed.get("primary_intent")
        if primary_intent not in intents:
            primary_intent = execution_order[0]

        return AgentIntent(
            primary_intent=primary_intent,
            intents=intents,
            execution_order=execution_order,
            confidence=float(parsed.get("confidence", fallback.confidence)),
            recommendation=RecommendationIntentContext(
                occasion=str(recommendation.get("occasion") or fallback.recommendation.occasion),
                preferred_style=self._nullable_string(recommendation.get("preferred_style"), fallback.recommendation.preferred_style),
                preferred_color=self._nullable_string(recommendation.get("preferred_color"), fallback.recommendation.preferred_color),
                temperature_f=float(recommendation.get("temperature_f", fallback.recommendation.temperature_f)),
                limit=self._bounded_limit(int(recommendation.get("limit", fallback.recommendation.limit))),
                trip_days=self._nullable_int(recommendation.get("trip_days"), fallback.recommendation.trip_days),
            ),
            reasoning_summary=str(parsed.get("reasoning_summary") or fallback.reasoning_summary),
            raw_message=message,
        )

    def _normalize_intent_list(self, values: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
        if not isinstance(values, list):
            return fallback
        normalized = [value for value in values if value in {IntentName.RECOMMEND, IntentName.SUMMARY, IntentName.ADVICE}]
        return tuple(normalized or fallback)

    def _normalize_execution_order(
        self,
        values: Any,
        intents: tuple[str, ...],
        fallback: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not isinstance(values, list):
            return tuple(skill for skill in fallback if skill in intents) or intents
        filtered = [value for value in values if value in intents]
        remaining = [intent for intent in intents if intent not in filtered]
        ordered = filtered + remaining
        return tuple(ordered or fallback)

    def _nullable_string(self, value: Any, fallback: str | None) -> str | None:
        if value is None:
            return fallback
        normalized = str(value).strip()
        return normalized or None

    def _nullable_int(self, value: Any, fallback: int | None) -> int | None:
        if value is None:
            return fallback
        try:
            return self._bounded_limit(int(value))
        except (TypeError, ValueError):
            return fallback

    def _bounded_limit(self, value: int) -> int:
        return max(1, min(value, 10))
