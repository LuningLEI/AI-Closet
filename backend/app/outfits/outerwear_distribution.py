"""Read-only shadow distribution for optional outerwear selection.

This module is deliberately not imported by the production generation path.
It makes the current candidate evidence inspectable before any rollout changes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import exp
import random
import re
from typing import Iterable

from app.models.domain import ClothingItemRecord
from app.outfits.compatibility import compatibility_issues, slot
from app.outfits.config import CompatibilityRules
from app.services.recommendation.rules import layers_compatible
from app.services.taste_profile import item_taste_score
from app.services.layering_fit import (
    assess_layering_pair,
    inner_bulk as production_inner_bulk,
    outer_capacity as production_outer_capacity,
)


SHADOW_POLICY_VERSION = "outerwear-shadow-v1"


@dataclass(frozen=True)
class OuterwearShadowConfig:
    softmax_temperature: float = 0.75
    temperature_f: float = 60.0
    occasion: str = "Everyday"


@dataclass
class OuterwearCandidateScore:
    outerwear_id: str | None
    inner_bulk: str
    outer_capacity: str
    capability_score: float
    fit_score: float
    sleeve_score: float
    material_score: float
    style_score: float
    occasion_score: float
    weather_score: float
    taste_score: float
    total_score: float
    masked: bool
    mask_reasons: list[str]
    probability: float = 0.0
    probability_rank: int = 0
    shadow_selected: bool = False

    def row(self) -> dict:
        value = asdict(self)
        value["mask_reasons"] = " | ".join(self.mask_reasons)
        return value


def upper_inner_items(base_items: Iterable[ClothingItemRecord]) -> list[ClothingItemRecord]:
    return [item for item in base_items if slot(item) in {"Tops", "FullBody"}]


def infer_inner_bulk(items: Iterable[ClothingItemRecord]) -> tuple[str, float]:
    levels = [_inner_bulk_value(item) for item in items]
    value = max(levels, default=1.0)
    return _level_label(value, (0.75, 1.5), ("light", "regular", "bulky")), value


def infer_outer_capacity(item: ClothingItemRecord) -> tuple[str, float]:
    _, value = production_outer_capacity(item)
    return _level_label(value, (0.75, 1.5), ("tight", "regular", "roomy")), value


def outerwear_distribution(
    base_items: list[ClothingItemRecord],
    outerwear: list[ClothingItemRecord],
    *,
    config: OuterwearShadowConfig | None = None,
    taste_profile: dict | None = None,
    compatibility_rules: CompatibilityRules | None = None,
    seed: str = "outerwear-shadow",
) -> list[OuterwearCandidateScore]:
    config = config or OuterwearShadowConfig()
    if config.softmax_temperature <= 0:
        raise ValueError("softmax_temperature must be positive")
    rules = compatibility_rules or CompatibilityRules()
    inners = upper_inner_items(base_items)
    bulk_label, bulk_value = infer_inner_bulk(inners)
    scored = [
        _score_outerwear(base_items, inners, bulk_label, bulk_value, candidate, config, taste_profile, rules)
        for candidate in outerwear
        if candidate.id not in {item.id for item in base_items} and slot(candidate) == "Outerwear"
    ]
    scored.append(_score_none(bulk_label, config))
    _assign_probabilities(scored, config.softmax_temperature)
    _select(scored, seed)
    return sorted(scored, key=lambda row: (row.probability_rank, row.outerwear_id or ""))


def _score_outerwear(base, inners, bulk_label, bulk_value, outer, config, taste_profile, rules):
    capacity_label, capacity_value = infer_outer_capacity(outer)
    mask_reasons = []
    pairwise = [assess_layering_pair(inner, outer) for inner in inners]
    if not inners:
        mask_reasons.append("no_upper_inner_item")
    elif any(not layers_compatible(inner, outer) for inner in inners):
        mask_reasons.append("production_layer_capability_rule")
    if any(assessment.hard_failure for assessment in pairwise):
        mask_reasons.append("production_pairwise_capacity_rule")
    issues = compatibility_issues(base + [outer], rules)
    if issues:
        mask_reasons.append("production_compatibility_rule")

    capability = _capability_score(inners, outer)
    pairwise_score = min((assessment.score for assessment in pairwise), default=capacity_value - bulk_value)
    fit = 1.0 if pairwise_score >= 0 else 0.0 if pairwise_score > -1 else -1.0
    sleeve = _sleeve_score(inners, capacity_value, bulk_value)
    material = _material_score(inners, capacity_value)
    style = _style_score(base, outer)
    occasion = _occasion_score(base, outer, config.occasion)
    weather = _weather_score(outer, config.temperature_f)
    taste = max(-1.0, min(1.0, item_taste_score(outer, taste_profile) / 10.0))
    total = (
        1.5 * capability
        + 2.0 * fit
        + 0.5 * sleeve
        + 0.5 * material
        + 0.6 * style
        + 0.5 * occasion
        + 0.8 * weather
        + 0.4 * taste
    )
    return OuterwearCandidateScore(
        outerwear_id=outer.id,
        inner_bulk=bulk_label,
        outer_capacity=capacity_label,
        capability_score=round(capability, 4),
        fit_score=round(fit, 4),
        sleeve_score=round(sleeve, 4),
        material_score=round(material, 4),
        style_score=round(style, 4),
        occasion_score=round(occasion, 4),
        weather_score=round(weather, 4),
        taste_score=round(taste, 4),
        total_score=round(total, 4),
        masked=bool(mask_reasons),
        mask_reasons=mask_reasons,
    )


def _score_none(bulk_label: str, config: OuterwearShadowConfig) -> OuterwearCandidateScore:
    if config.temperature_f >= 78:
        weather = 1.0
    elif config.temperature_f >= 65:
        weather = 0.5
    elif config.temperature_f >= 50:
        weather = 0.0
    else:
        weather = -1.0
    return OuterwearCandidateScore(
        outerwear_id=None,
        inner_bulk=bulk_label,
        outer_capacity="none",
        capability_score=0.0,
        fit_score=0.0,
        sleeve_score=0.0,
        material_score=0.0,
        style_score=0.0,
        occasion_score=0.0,
        weather_score=weather,
        taste_score=0.0,
        total_score=round(0.8 * weather, 4),
        masked=False,
        mask_reasons=[],
    )


def _assign_probabilities(rows: list[OuterwearCandidateScore], temperature: float) -> None:
    eligible = [row for row in rows if not row.masked]
    if not eligible:
        return
    maximum = max(row.total_score / temperature for row in eligible)
    weights = [exp(row.total_score / temperature - maximum) for row in eligible]
    denominator = sum(weights)
    for row, weight in zip(eligible, weights, strict=True):
        row.probability = weight / denominator
    for rank, row in enumerate(sorted(rows, key=lambda value: (-value.probability, value.outerwear_id or "")), start=1):
        row.probability_rank = rank


def _select(rows: list[OuterwearCandidateScore], seed: str) -> None:
    eligible = [row for row in rows if row.probability > 0]
    if not eligible:
        return
    threshold = random.Random(seed).random()
    cumulative = 0.0
    for row in eligible:
        cumulative += row.probability
        if threshold <= cumulative:
            row.shadow_selected = True
            return
    eligible[-1].shadow_selected = True


def _inner_bulk_value(item: ClothingItemRecord) -> float:
    return production_inner_bulk(item)[1]


def _capability_score(inners: list[ClothingItemRecord], outer: ClothingItemRecord) -> float:
    if not inners:
        return -1.0
    inner_values = [item.wearing_profile.get("can_layer_under") for item in inners]
    outer_value = outer.wearing_profile.get("can_layer_over")
    if False in inner_values or outer_value is False:
        return -1.0
    if all(value is True for value in inner_values) and outer_value is True:
        return 1.0
    return 0.4


def _sleeve_score(inners: list[ClothingItemRecord], capacity: float, bulk: float) -> float:
    sleeves = " ".join((item.sleeve_length or "") for item in inners).lower()
    if bulk >= 1.5 and capacity <= 0.75 and any(token in sleeves for token in ("long", "balloon", "puff")):
        return -1.0
    return 1.0 if capacity >= bulk else 0.25


def _material_score(inners: list[ClothingItemRecord], capacity: float) -> float:
    materials = " ".join((item.material or "") for item in inners).lower()
    bulky = _contains(materials, "wool", "fleece", "chunky", "boucle", "sherpa", "thick knit")
    if bulky and capacity <= 0.75:
        return -1.0
    return 1.0 if not bulky or capacity >= 1.5 else 0.25


def _style_score(base: list[ClothingItemRecord], outer: ClothingItemRecord) -> float:
    values = {item.style.strip().casefold() for item in base if item.style and item.style.strip()}
    if not values or not outer.style:
        return 0.0
    return 1.0 if outer.style.strip().casefold() in values else 0.0


def _occasion_score(base: list[ClothingItemRecord], outer: ClothingItemRecord, requested: str) -> float:
    requested_value = requested.strip().casefold()
    outer_values = _tokens(outer.occasion)
    if requested_value and requested_value in outer_values:
        return 1.0
    base_values = set().union(*(_tokens(item.occasion) for item in base)) if base else set()
    return 0.5 if outer_values & base_values else 0.0


def _weather_score(item: ClothingItemRecord, temperature_f: float) -> float:
    target = 5.0 if temperature_f < 45 else 3.5 if temperature_f < 65 else 2.0 if temperature_f < 78 else 1.0
    warmth = float(item.warmth_level) if item.warmth_level is not None else _inferred_warmth(item)
    return max(-1.0, min(1.0, 1.0 - abs(warmth - target) / 2.5))


def _inferred_warmth(item: ClothingItemRecord) -> float:
    descriptor = _descriptor(item)
    if _contains(descriptor, "puffer", "parka", "down", "sherpa", "wool coat"):
        return 5.0
    if _contains(descriptor, "coat", "fleece", "heavy jacket"):
        return 4.0
    if _contains(descriptor, "cardigan", "blazer", "jacket", "windbreaker", "trench"):
        return 3.0
    return 2.0


def _descriptor(item: ClothingItemRecord) -> str:
    return " ".join(
        str(value or "")
        for value in (item.category, item.subtype, item.fit, item.material, item.sleeve_length, item.recognition_summary)
    ).casefold()


def _contains(value: str, *tokens: str) -> bool:
    return any(re.search(rf"\b{re.escape(token)}\b", value) for token in tokens)


def _tokens(value: str | None) -> set[str]:
    return {token.strip().casefold() for token in (value or "").split(",") if token.strip()}


def _level_label(value: float, thresholds: tuple[float, float], labels: tuple[str, str, str]) -> str:
    if value < thresholds[0]:
        return labels[0]
    if value < thresholds[1]:
        return labels[1]
    return labels[2]
