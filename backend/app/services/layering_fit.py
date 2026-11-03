"""Deterministic pairwise upper-body layering fit.

Capability answers whether a garment may be used in a direction.  This module
separately estimates whether one *specific* inner/outer pair has enough physical
room.  It uses persisted recognition metadata only and never calls a model.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import ClothingItemRecord


class LayeringFitPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "layering-fit-v1"
    hard_failure_threshold: float = Field(default=-1.5, le=-0.5, allow_inf_nan=False)
    penalty_points_per_gap: float = Field(default=8.0, ge=0, le=20, allow_inf_nan=False)
    maximum_penalty_points: float = Field(default=20.0, ge=0, le=40, allow_inf_nan=False)
    hoodie_restrictive_outer_penalty: float = Field(default=1.2, ge=0, le=3, allow_inf_nan=False)
    hoodie_stiff_jacket_penalty: float = Field(default=0.9, ge=0, le=3, allow_inf_nan=False)
    bulky_restrictive_outer_penalty: float = Field(default=0.8, ge=0, le=3, allow_inf_nan=False)
    roomy_outer_bonus: float = Field(default=0.3, ge=0, le=2, allow_inf_nan=False)


@dataclass(frozen=True)
class LayeringFitAssessment:
    score: float
    penalty: float
    hard_failure: bool
    inner_bulk: str
    outer_capacity: str
    material_stiffness: str
    reasons: tuple[str, ...]


def upper_layering_items(items: list[ClothingItemRecord]) -> tuple[list[ClothingItemRecord], list[ClothingItemRecord]]:
    from app.services.recommendation.rules import recommendation_slot

    inners = [item for item in items if recommendation_slot(item.category, item.subtype) in {"Tops", "FullBody"}]
    outers = [item for item in items if recommendation_slot(item.category, item.subtype) == "Outerwear"]
    return inners, outers


def assess_layering_pair(
    inner: ClothingItemRecord,
    outer: ClothingItemRecord,
    policy: LayeringFitPolicy | None = None,
) -> LayeringFitAssessment:
    policy = policy or LayeringFitPolicy()
    inner_label, bulk = inner_bulk(inner)
    outer_label, capacity = outer_capacity(outer)
    stiffness_label, stiffness = material_stiffness(outer)
    reasons: list[str] = []

    inner_capability = inner.wearing_profile.get("can_layer_under")
    outer_capability = outer.wearing_profile.get("can_layer_over")
    if inner_capability is False:
        reasons.append("inner garment explicitly cannot layer underneath")
    if outer_capability is False:
        reasons.append("outer garment explicitly cannot layer over another garment")
    if reasons:
        return LayeringFitAssessment(
            score=-4.0,
            penalty=policy.maximum_penalty_points,
            hard_failure=True,
            inner_bulk=inner_label,
            outer_capacity=outer_label,
            material_stiffness=stiffness_label,
            reasons=tuple(reasons),
        )

    descriptor = _descriptor(inner)
    outer_descriptor = _descriptor(outer)
    subtype = (outer.subtype or "").casefold()
    roomy = capacity >= 1.75
    score = capacity - bulk - stiffness

    if _contains(descriptor, "hoodie"):
        if subtype in {"cardigan", "vest"} and not roomy:
            score -= policy.hoodie_restrictive_outer_penalty
            reasons.append("hoodie volume conflicts with a restrictive cardigan or vest")
        if _contains(outer_descriptor, "jacket") and stiffness >= 0.3 and not roomy:
            score -= policy.hoodie_stiff_jacket_penalty
            reasons.append("hoodie volume conflicts with a structured or stiff jacket")
    if bulk >= 1.5 and subtype in {"cardigan", "vest"} and not roomy:
        score -= policy.bulky_restrictive_outer_penalty
        reasons.append("bulky inner layer needs more room than this cardigan or vest provides")
    if sleeve_volume(inner) == "voluminous" and capacity < 1.25:
        score -= 0.5
        reasons.append("voluminous inner sleeves need more outer sleeve room")
    if roomy and subtype in {"coat", "puffer", "cape", "parka", "ski jacket"}:
        score += policy.roomy_outer_bonus

    score = round(score, 4)
    hard_failure = score <= policy.hard_failure_threshold
    if hard_failure and not reasons:
        reasons.append("inner volume exceeds estimated outerwear capacity")
    penalty = min(policy.maximum_penalty_points, max(0.0, -score) * policy.penalty_points_per_gap)
    return LayeringFitAssessment(
        score=score,
        penalty=round(penalty, 4),
        hard_failure=hard_failure,
        inner_bulk=inner_label,
        outer_capacity=outer_label,
        material_stiffness=stiffness_label,
        reasons=tuple(reasons),
    )


def assess_outfit_layering(
    items: list[ClothingItemRecord],
    policy: LayeringFitPolicy | None = None,
) -> LayeringFitAssessment | None:
    inners, outers = upper_layering_items(items)
    if not inners or not outers:
        return None
    assessments = [assess_layering_pair(inner, outer, policy) for inner in inners for outer in outers]
    return min(assessments, key=lambda assessment: assessment.score)


def inner_bulk(item: ClothingItemRecord) -> tuple[str, float]:
    explicit = item.wearing_profile.get("layering_bulk")
    if explicit in {"low", "medium", "high"}:
        value = {"low": 0.5, "medium": 1.0, "high": 2.0}[explicit]
        return explicit, value

    descriptor = _descriptor(item)
    value = 1.0
    if _contains(descriptor, "camisole", "tank", "t-shirt", "tee", "blouse", "shirt", "bodysuit", "mesh"):
        value = 0.5
    if _contains(descriptor, "pullover", "sweater", "sweatshirt", "fleece", "chunky", "cable knit"):
        value = 1.5
    if _contains(descriptor, "hoodie"):
        value = 1.8
    if _contains(descriptor, "oversized", "relaxed", "loose", "boxy"):
        value += 0.4
    if _contains(descriptor, "fitted", "slim", "tight", "bodycon"):
        value -= 0.3
    if hood_volume(item) == "high":
        value += 0.2
    if sleeve_volume(item) == "voluminous":
        value += 0.25
    value = max(0.25, min(2.5, value))
    return _level(value, 0.75, 1.5, "low", "medium", "high"), value


def outer_capacity(item: ClothingItemRecord) -> tuple[str, float]:
    explicit = item.wearing_profile.get("outer_capacity")
    if explicit in {"low", "medium", "high"}:
        value = {"low": 0.5, "medium": 1.25, "high": 2.25}[explicit]
        return explicit, value

    descriptor = _descriptor(item)
    subtype = (item.subtype or "").casefold()
    value = 1.1
    if _contains(descriptor, "slim", "fitted", "tight", "shrunken", "bodycon", "tailored"):
        value = 0.5
    elif _contains(descriptor, "oversized", "relaxed", "loose", "roomy", "boxy"):
        value = 2.1
    elif subtype in {"puffer", "parka", "coat", "cape", "ski jacket"}:
        value = 2.0
    elif subtype in {"cardigan", "vest", "blazer"}:
        value = 0.9
    return _level(value, 0.85, 1.75, "low", "medium", "high"), value


def material_stiffness(item: ClothingItemRecord) -> tuple[str, float]:
    explicit = item.wearing_profile.get("material_stiffness")
    if explicit in {"soft", "medium", "stiff"}:
        value = {"soft": 0.0, "medium": 0.15, "stiff": 0.35}[explicit]
        return explicit, value
    descriptor = _descriptor(item)
    if _contains(descriptor, "denim", "leather", "twill", "structured", "rigid"):
        return "stiff", 0.35
    if _contains(descriptor, "knit", "jersey", "fleece", "stretch"):
        return "soft", 0.0
    return "medium", 0.15


def hood_volume(item: ClothingItemRecord) -> str:
    explicit = item.wearing_profile.get("hood_volume")
    if explicit in {"none", "low", "high"}:
        return explicit
    return "high" if _contains(_descriptor(item), "hoodie", "large hood", "oversized hood") else "none"


def sleeve_volume(item: ClothingItemRecord) -> str:
    explicit = item.wearing_profile.get("sleeve_volume")
    if explicit in {"slim", "regular", "voluminous"}:
        return explicit
    descriptor = _descriptor(item)
    if _contains(descriptor, "balloon sleeve", "puff sleeve", "bishop sleeve", "wide sleeve"):
        return "voluminous"
    if _contains(descriptor, "slim", "fitted", "tight"):
        return "slim"
    return "regular"


def _descriptor(item: ClothingItemRecord) -> str:
    return " ".join(
        str(value or "")
        for value in (
            item.category,
            item.subtype,
            item.fit,
            item.material,
            item.sleeve_length,
            item.recognition_summary,
        )
    ).casefold()


def _contains(value: str, *tokens: str) -> bool:
    return any(re.search(rf"\b{re.escape(token)}\b", value) for token in tokens)


def _level(value: float, lower: float, upper: float, low: str, medium: str, high: str) -> str:
    if value < lower:
        return low
    if value < upper:
        return medium
    return high
