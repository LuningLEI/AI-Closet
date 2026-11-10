"""Strict, provider-facing recognition output contract.

This model intentionally contains only values the vision model may return.  It
is separate from ``ClothingAnalysis``, which also contains persistence,
normalization and audit fields owned by the application.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from app.core.constants import (
    FORMALITY_SCORE_MAX,
    FORMALITY_SCORE_MIN,
    MODEL_CONFIDENCE_MAX,
    MODEL_CONFIDENCE_MIN,
    WARMTH_LEVEL_MAX,
    WARMTH_LEVEL_MIN,
)
from app.models.domain import WearingProfile
from app.services.taxonomy import CATEGORIES, COLORS, LENGTHS, OCCASIONS, SEASONS, SLEEVE_LENGTHS, STYLES, SUBTYPES


RecognitionWarning = Literal["multiple_clothing_items", "non_clothing_image", "poor_visibility"]


class RecognitionColorTone(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    color: str
    hue: float | None = Field(ge=0, le=360, allow_inf_nan=False)
    saturation: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    lightness: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    evidence: str | None = Field(max_length=500)

    @field_validator("evidence", mode="before")
    @classmethod
    def nullable_text_is_not_a_sentinel(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() in {"null", "none", "unknown"}:
            raise ValueError("uncertain optional text must use JSON null")
        return value


class RecognitionOccasionScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    occasion: str
    score: float = Field(ge=0, le=1, allow_inf_nan=False)


class RecognitionWearingProfile(BaseModel):
    """Required-key version of the domain wearing profile for model output."""

    model_config = ConfigDict(extra="forbid", strict=True)

    layering_region: Literal["upper_body", "lower_body", "full_body"] | None
    lower_layer_role: Literal["base", "outer"] | None
    can_wear_alone: StrictBool | None
    can_layer_over: StrictBool | None
    can_layer_under: StrictBool | None
    requires_inner_layer: StrictBool | None
    closure_type: Literal["pullover", "buttons", "zipper", "open_front", "wrap", "other"] | None
    layering_bulk: Literal["low", "medium", "high"] | None
    outer_capacity: Literal["low", "medium", "high"] | None
    material_stiffness: Literal["soft", "medium", "stiff"] | None
    hood_volume: Literal["none", "low", "high"] | None
    sleeve_volume: Literal["slim", "regular", "voluminous"] | None
    wearing_modes: list[Literal["standalone", "inner_layer", "outer_layer_closed", "outer_layer_open"]]
    evidence: str | None = Field(max_length=500)

    @field_validator("evidence", mode="before")
    @classmethod
    def nullable_text_is_not_a_sentinel(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() in {"null", "none", "unknown"}:
            raise ValueError("uncertain optional text must use JSON null")
        return value

    @model_validator(mode="after")
    def validate_domain_semantics(self) -> RecognitionWearingProfile:
        # Keep one implementation of the cross-field layering rules.
        WearingProfile.model_validate(self.model_dump())
        if len(self.wearing_modes) != len(set(self.wearing_modes)):
            raise ValueError("wearing_modes must not contain duplicates")
        return self


class RecognitionCandidateV1(BaseModel):
    """Canonical strict output for one primary garment in an image."""

    model_config = ConfigDict(extra="forbid", strict=True)

    category: str
    subtype: str | None
    color: str
    color_tones: list[RecognitionColorTone]
    seasons: list[str]
    style: str
    occasion_scores: list[RecognitionOccasionScore]
    material: str | None = Field(max_length=100)
    pattern: str | None = Field(max_length=100)
    fit: str | None = Field(max_length=100)
    length: str | None
    sleeve_length: str | None
    neckline: str | None = Field(max_length=100)
    layering_role: str | None = Field(max_length=100)
    wearing_profile: RecognitionWearingProfile
    warmth_level: int | None = Field(ge=WARMTH_LEVEL_MIN, le=WARMTH_LEVEL_MAX)
    formality_score: int | None = Field(ge=FORMALITY_SCORE_MIN, le=FORMALITY_SCORE_MAX)
    confidence: float | None = Field(ge=MODEL_CONFIDENCE_MIN, le=MODEL_CONFIDENCE_MAX, allow_inf_nan=False)
    notes: str | None = Field(max_length=500)
    warnings: list[RecognitionWarning]

    @field_validator(
        "material",
        "pattern",
        "fit",
        "length",
        "sleeve_length",
        "neckline",
        "layering_role",
        "notes",
        mode="before",
    )
    @classmethod
    def nullable_text_is_not_a_sentinel(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip().casefold() in {"null", "none", "unknown"}:
            raise ValueError("uncertain optional text must use JSON null")
        return value

    @field_validator("seasons", "warnings")
    @classmethod
    def unique_nonempty_lists(cls, value: list[str], info: Any) -> list[str]:
        if info.field_name == "seasons" and not value:
            raise ValueError("seasons must contain at least one value")
        if len(value) != len(set(value)):
            raise ValueError(f"{info.field_name} must not contain duplicates")
        return value


def resolve_recognition_taxonomy(
    *,
    allowed_categories: list[str] | None = None,
    allowed_taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = allowed_taxonomy or {}
    categories = list(allowed_categories or catalog.get("categories") or CATEGORIES)
    raw_subtype_overrides = catalog.get("subtypes")
    subtype_overrides: dict[str, Any] = raw_subtype_overrides if isinstance(raw_subtype_overrides, dict) else {}
    return {
        "categories": categories,
        "subtypes": {
            category: list(subtype_overrides.get(category) or SUBTYPES.get(category, ["Unknown"]))
            for category in categories
        },
        "colors": list(catalog.get("colors") or COLORS),
        "styles": list(catalog.get("styles") or STYLES),
        "occasions": list(catalog.get("occasions") or OCCASIONS),
        "seasons": list(catalog.get("seasons") or SEASONS),
        "lengths": list(catalog.get("lengths") or LENGTHS),
        "sleeve_lengths": list(catalog.get("sleeve_lengths") or SLEEVE_LENGTHS),
    }


def recognition_candidate_schema(taxonomy: dict[str, Any]) -> dict[str, Any]:
    """Return a provider schema constrained to the latest user taxonomy."""

    schema = deepcopy(RecognitionCandidateV1.model_json_schema())
    properties = schema["properties"]
    properties["category"] = {"type": "string", "enum": taxonomy["categories"]}
    subtype_values = list(dict.fromkeys(
        value
        for category in taxonomy["categories"]
        for value in taxonomy["subtypes"].get(category, ["Unknown"])
    ))
    properties["subtype"] = {
        "anyOf": [{"type": "string", "enum": subtype_values}, {"type": "null"}],
    }
    properties["style"] = {"type": "string", "enum": taxonomy["styles"]}
    properties["seasons"]["items"] = {"type": "string", "enum": taxonomy["seasons"]}
    properties["length"] = {
        "anyOf": [{"type": "string", "enum": taxonomy["lengths"]}, {"type": "null"}],
    }
    properties["sleeve_length"] = {
        "anyOf": [{"type": "string", "enum": taxonomy["sleeve_lengths"]}, {"type": "null"}],
    }
    definitions = schema.get("$defs", {})
    definitions["RecognitionColorTone"]["properties"]["color"] = {
        "type": "string",
        "enum": taxonomy["colors"],
    }
    definitions["RecognitionOccasionScore"]["properties"]["occasion"] = {
        "type": "string",
        "enum": taxonomy["occasions"],
    }
    return schema


def validate_candidate_taxonomy(candidate: RecognitionCandidateV1, taxonomy: dict[str, Any]) -> None:
    """Apply dynamic and cross-field constraints not expressible portably in JSON Schema."""

    if candidate.category not in taxonomy["categories"]:
        raise ValueError(f"category is not in the user taxonomy: {candidate.category}")
    allowed_subtypes = taxonomy["subtypes"].get(candidate.category, ["Unknown"])
    if candidate.subtype is not None and candidate.subtype not in allowed_subtypes:
        raise ValueError(f"subtype is invalid for {candidate.category}: {candidate.subtype}")

    colors = [value.strip() for value in candidate.color.split(",") if value.strip()]
    if not colors or len(colors) != len(set(colors)):
        raise ValueError("color must contain one or more distinct comma-separated labels")
    if any(color not in taxonomy["colors"] for color in colors):
        raise ValueError("color contains a label outside the user taxonomy")
    if "Unknown" in colors and len(colors) > 1:
        raise ValueError("Unknown cannot be combined with a known color")
    if any(tone.color not in colors for tone in candidate.color_tones):
        raise ValueError("each color_tones color must also appear in color")

    if candidate.style not in taxonomy["styles"]:
        raise ValueError(f"style is not in the user taxonomy: {candidate.style}")
    if any(season not in taxonomy["seasons"] for season in candidate.seasons):
        raise ValueError("seasons contains a label outside the user taxonomy")
    if candidate.length is not None and candidate.length not in taxonomy["lengths"]:
        raise ValueError(f"length is not in the user taxonomy: {candidate.length}")
    if candidate.sleeve_length is not None and candidate.sleeve_length not in taxonomy["sleeve_lengths"]:
        raise ValueError(f"sleeve_length is not in the user taxonomy: {candidate.sleeve_length}")

    actual_occasions = [entry.occasion for entry in candidate.occasion_scores]
    if len(actual_occasions) != len(set(actual_occasions)):
        raise ValueError("occasion_scores must not contain duplicate labels")
    if set(actual_occasions) != set(taxonomy["occasions"]):
        raise ValueError("occasion_scores must contain every user occasion exactly once")
