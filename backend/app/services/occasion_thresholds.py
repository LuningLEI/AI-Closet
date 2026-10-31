"""Per-user occasion policy storage; future learning code can call update_user_thresholds."""
import math

from app.core.config import settings
from app.services.taxonomy import OCCASIONS


def validate_thresholds(values: dict) -> dict[str, float]:
    if not isinstance(values, dict):
        raise ValueError('Occasion thresholds must be an object.')
    values = dict(values)
    if 'Vacation' in values:
        values.setdefault('Travel',values.pop('Vacation'))
    for label, value in values.items():
        if label not in OCCASIONS:
            raise ValueError(f'Unknown occasion: {label}')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f'Threshold for {label} must be a finite number between 0 and 1.')
    return {label: float(value) for label, value in values.items()}


def resolve_thresholds(preferences: dict | None = None) -> dict[str, float]:
    preferences=preferences or {};values=preferences.get('occasion_thresholds', {})
    custom=(((preferences.get('taxonomy') or {}).get('customizations') or {}).get('occasions') or [])
    labels=list(dict.fromkeys(OCCASIONS+[label for label in custom if isinstance(label,str) and label.strip()]))
    return {**dict.fromkeys(labels, settings.recognition_occasion_threshold), **validate_thresholds(values)}


def user_thresholds(repository, user_id: str) -> dict[str, float]:
    return resolve_thresholds(repository.get_preferences(user_id).get('preferences', {}))


def update_user_thresholds(repository, user_id: str, changes: dict[str, float]) -> dict[str, float]:
    changes = validate_thresholds(changes)
    record = repository.get_preferences(user_id)
    preferences = dict(record.get('preferences') or {})
    thresholds = {**resolve_thresholds(preferences), **changes}
    preferences['occasion_thresholds'] = thresholds
    repository.upsert_preferences(user_id, {'preferences': preferences})
    return thresholds
