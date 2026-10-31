"""Derive display/recommendation labels without modifying stored recognition scores."""
from __future__ import annotations

import math

from app.core.config import settings
from app.core.constants import RecognitionSource, RecognitionStatus
from app.models.domain import ClothingItemRecord
from app.services.taxonomy import OCCASIONS
from app.services.catalog_support import canonical_occasion, canonical_occasions


def is_manual(item: ClothingItemRecord) -> bool:
    return (item.recognition_status == RecognitionStatus.MANUAL
            or item.recognition_source == RecognitionSource.MANUAL_EDIT
            or bool((item.metadata or {}).get('manual_override')))


def occasion_set(value: str) -> set[str]:
    return {canonical_occasion(label) for label in value.split(',') if label.strip()}


def select_scored_occasions(scores: dict[str, float], threshold: float | dict[str, float], order:list[str]|None=None) -> list[str]:
    """Keep all passing labels, or one highest score if none pass; ties use taxonomy order."""
    order=order or OCCASIONS;positions={label:index for index,label in enumerate(order)}
    ranked = sorted(scores, key=lambda label: (-scores[label], positions.get(label,len(order))))
    selected = [label for label in ranked if scores[label] >= (threshold.get(label,settings.recognition_occasion_threshold) if isinstance(threshold, dict) else threshold)]
    return selected or ranked[:1]


def model_occasions(item: ClothingItemRecord, threshold: float | dict[str, float] | None = None) -> list[str] | None:
    values = (item.recognition_tags or {}).get('occasion_scores')
    if not isinstance(values, list) or not values:
        return None  # Legacy results and heuristic fallbacks have no scores.
    scores: dict[str, float] = {};allowed=list(threshold) if isinstance(threshold,dict) else OCCASIONS
    for entry in values:
        if not isinstance(entry, dict):
            continue
        label, score = canonical_occasion(entry.get('occasion')), entry.get('score')
        if (label not in allowed or isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score) or not 0 <= score <= 1):
            continue
        scores[label] = max(scores.get(label, 0), score)
    if not scores:
        return None
    cutoff = threshold if threshold is not None else (
        (item.recognition_tags or {}).get('display_occasion_thresholds') or settings.recognition_occasion_threshold
    )
    return select_scored_occasions(scores, cutoff,allowed)


def occasion_overrides(item: ClothingItemRecord,allowed:list[str]|None=None) -> dict[str, list[str]]:
    allowed=allowed or OCCASIONS
    value = (item.metadata or {}).get('occasion_overrides')
    if isinstance(value, dict):
        return {key: list(dict.fromkeys(canonical_occasion(label) for label in value.get(key, []) if canonical_occasion(label) in allowed))
                for key in ('added', 'removed')}
    if is_manual(item):
        # Older manual edits had no field-level history: preserve their exact selection.
        selected = occasion_set(item.occasion)
        return {'added': [label for label in allowed if label in selected],
                'removed': [label for label in allowed if label not in selected]}
    return {'added': [], 'removed': []}


def effective_occasion(item: ClothingItemRecord, threshold: float | dict[str, float] | None = None) -> str:
    if (item.metadata or {}).get('label_confirmation'):
        return canonical_occasions(item.occasion)
    overrides = (item.metadata or {}).get('occasion_overrides')
    if overrides is None and is_manual(item):
        return canonical_occasions(item.occasion)
    model = model_occasions(item, threshold)
    base = model if model is not None else list(dict.fromkeys(canonical_occasion(label) for label in item.occasion.split(',') if label.strip()))
    manual = occasion_overrides(item,list(threshold) if isinstance(threshold,dict) else OCCASIONS)
    selected = (set(base) | set(manual['added'])) - set(manual['removed'])
    ordered = list(dict.fromkeys(base + (list(threshold) if isinstance(threshold,dict) else OCCASIONS)))
    return ', '.join(label for label in ordered if label and label in selected)


def occasion_for_display(item: ClothingItemRecord, thresholds: dict[str, float] | None = None) -> ClothingItemRecord:
    updates = {'occasion': effective_occasion(item, thresholds)}
    if item.recognition_tags:
        updates['recognition_tags'] = {
            **item.recognition_tags,
            # Response-only value; the original recognition threshold remains an audit snapshot.
            'display_occasion_threshold': settings.recognition_occasion_threshold,
            **({'display_occasion_thresholds': thresholds} if thresholds is not None else {}),
        }
    return item.model_copy(update=updates)
