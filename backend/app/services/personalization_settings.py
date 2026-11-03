"""Stable user-facing controls for recommendation personalization.

The UI exposes named product choices, while this module owns their numeric
policy mapping.  Keeping that mapping server-side prevents iOS and workers
from silently drifting apart.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel


ExplorationLevel = Literal["familiar", "balanced", "adventurous"]
RotationLevel = Literal["repeat_freely", "balanced", "more_variety"]
TemperatureSensitivity = Literal["runs_cold", "neutral", "runs_warm"]


class PersonalizationSettings(BaseModel):
    personalization_enabled: bool = True
    feedback_learning_enabled: bool = True
    exploration_level: ExplorationLevel = "balanced"
    rotation_level: RotationLevel = "balanced"
    temperature_sensitivity: TemperatureSensitivity = "neutral"


DEFAULT_PERSONALIZATION_SETTINGS = PersonalizationSettings()


def resolve_personalization_settings(preferences: dict[str, Any] | None) -> PersonalizationSettings:
    raw = (preferences or {}).get("recommendation")
    if not isinstance(raw, dict):
        return DEFAULT_PERSONALIZATION_SETTINGS.model_copy()
    return PersonalizationSettings.model_validate(raw)


def with_personalization_settings(
    preferences: dict[str, Any], settings: PersonalizationSettings
) -> dict[str, Any]:
    result = deepcopy(preferences)
    result["recommendation"] = settings.model_dump()
    return result


def exploration_rate(settings: PersonalizationSettings) -> float:
    return {"familiar": 0.0, "balanced": 0.15, "adventurous": 0.30}[settings.exploration_level]


def effective_temperature_f(actual_temperature_f: float, settings: PersonalizationSettings) -> float:
    """Translate subjective comfort into an equivalent styling temperature."""
    adjustment = {"runs_cold": -5.0, "neutral": 0.0, "runs_warm": 5.0}
    return actual_temperature_f + adjustment[settings.temperature_sensitivity]
