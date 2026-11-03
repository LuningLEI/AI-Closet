from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.constants import DEFAULT_OCCASION, DEFAULT_STYLE
from app.core.versions import PROFILE_VERSION, STYLE_PREFERENCE_VERSION, TAXONOMY_VERSION
from app.services.taxonomy import CATEGORIES, default_user_preferences, merge_preferences, normalize_customizations
from app.services.personalization_settings import PersonalizationSettings

DEFAULT_DAILY_OCCASIONS = [DEFAULT_OCCASION, "Work"]
DEFAULT_STYLE_PREFERENCES = [DEFAULT_STYLE]


def default_preference_record(user_id: str) -> dict[str, Any]:
    return normalize_preference_record(
        {
            "user_id": user_id,
            "profile_version": PROFILE_VERSION,
            "taxonomy_version": TAXONOMY_VERSION,
            "style_preference_version": STYLE_PREFERENCE_VERSION,
            "default_location_label": None,
            "default_latitude": None,
            "default_longitude": None,
            "temperature_unit": "F",
            "preferences": default_user_preferences(),
        }
    )


def normalize_preference_updates(user_id: str, existing: dict[str, Any] | None, updates: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_preference_record(existing or {"user_id": user_id})
    payload.update({key: value for key, value in updates.items() if value is not None})
    if "preferences" in updates:
        if isinstance(updates["preferences"], dict) and "occasion_thresholds" not in updates["preferences"]:
            previous_thresholds = ((existing or {}).get("preferences") or {}).get("occasion_thresholds")
            if previous_thresholds is not None:
                payload["preferences"] = {**updates["preferences"], "occasion_thresholds": previous_thresholds}
        for key in (
            "onboarding_completed",
            "nickname",
            "avatar_path",
            "birth_year",
            "gender_identity",
            "daily_occasions",
            "style_preferences",
            "occasion_style_preferences",
            "selected_categories",
            "custom_categories",
            "taxonomy_customizations",
        ):
            if key not in updates:
                payload.pop(key, None)
    payload["user_id"] = user_id
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    return normalize_preference_record(payload)


def normalize_preference_record(record: dict[str, Any]) -> dict[str, Any]:
    user_id = str(record.get("user_id") or "")
    memory = merge_preferences(record.get("preferences"))
    profile = dict(memory.get("profile") or {})
    taxonomy = dict(memory.get("taxonomy") or {})

    nickname = _string_or_none(record.get("nickname")) or _string_or_none(profile.get("nickname"))
    avatar_path = _string_or_none(record.get("avatar_path")) or _string_or_none(profile.get("avatar_path"))
    birth_year = _int_or_none(record.get("birth_year") if record.get("birth_year") is not None else profile.get("birth_year"))
    gender_identity = _string_or_none(record.get("gender_identity")) or _string_or_none(profile.get("gender_identity"))

    daily_occasions = _string_list(record.get("daily_occasions"), None)
    if not daily_occasions:
        daily_occasions = _string_list(profile.get("daily_occasions"), DEFAULT_DAILY_OCCASIONS)

    style_preferences = _string_list(record.get("style_preferences"), None)
    if not style_preferences:
        style_preferences = _string_list(profile.get("style_preferences"), DEFAULT_STYLE_PREFERENCES)

    raw_occasion_styles = record.get("occasion_style_preferences")
    raw_memory = record.get("preferences") if isinstance(record.get("preferences"), dict) else {}
    raw_profile = raw_memory.get("profile") if isinstance(raw_memory.get("profile"), dict) else {}
    if not isinstance(raw_occasion_styles, dict):
        # Read the unmerged profile so the defaults do not mask legacy flat
        # preferences that still need to be expanded across occasions.
        raw_occasion_styles = raw_profile.get("occasion_style_preferences")
    occasion_style_preferences = _occasion_style_map(
        raw_occasion_styles,
        daily_occasions,
        style_preferences,
    )
    # Retain the legacy field as a stable union for older clients and jobs.
    style_preferences = list(dict.fromkeys(
        style for occasion in daily_occasions for style in occasion_style_preferences[occasion]
    ))

    selected_categories = _string_list(record.get("selected_categories"), None)
    if not selected_categories:
        selected_categories = _string_list(taxonomy.get("selected_categories"), CATEGORIES)

    custom_categories = _string_list(record.get("custom_categories"), None)
    if custom_categories is None:
        custom_categories = _string_list(taxonomy.get("custom_categories"), [])

    taxonomy_customizations = record.get("taxonomy_customizations")
    if not isinstance(taxonomy_customizations, dict):
        taxonomy_customizations = taxonomy.get("customizations")
    if not isinstance(taxonomy_customizations, dict):
        taxonomy_customizations = {}
    taxonomy_customizations = normalize_customizations(taxonomy_customizations,selected_categories+custom_categories)

    onboarding_completed = _bool_value(
        _record_value(record, "onboarding_completed"),
        bool(memory.get("onboarding_completed", False)),
    )
    model_training_consent = _bool_value(record.get("model_training_consent"), False)
    recommendation = dict(memory.get("recommendation") or {})
    for key in (
        "personalization_enabled",
        "feedback_learning_enabled",
        "exploration_level",
        "rotation_level",
        "temperature_sensitivity",
    ):
        if record.get(key) is not None:
            recommendation[key] = record[key]
    personalization = PersonalizationSettings.model_validate(recommendation)

    profile_version = str(record.get("profile_version") or PROFILE_VERSION)
    taxonomy_version = str(record.get("taxonomy_version") or TAXONOMY_VERSION)
    style_preference_version = str(record.get("style_preference_version") or STYLE_PREFERENCE_VERSION)

    profile.update(
        {
            "nickname": nickname,
            "avatar_path": avatar_path,
            "birth_year": birth_year,
            "gender_identity": gender_identity,
            "daily_occasions": daily_occasions,
            "style_preferences": style_preferences,
            "occasion_style_preferences": occasion_style_preferences,
        }
    )
    taxonomy.update(
        {
            "selected_categories": selected_categories,
            "custom_categories": custom_categories,
            "customizations": taxonomy_customizations,
        }
    )
    memory.update(
        {
            "onboarding_completed": onboarding_completed,
            "profile": profile,
            "taxonomy": taxonomy,
            "recommendation": personalization.model_dump(),
            "schema_versions": {
                "profile": profile_version,
                "taxonomy": taxonomy_version,
                "style_preference": style_preference_version,
            },
        }
    )

    profile_features = record.get("profile_features")
    if not isinstance(profile_features, dict):
        profile_features = {}
    profile_features.update(
        {
            "birth_year": birth_year,
            "gender_identity": gender_identity,
            "daily_occasions": daily_occasions,
            "style_preferences": style_preferences,
            "occasion_style_preferences": occasion_style_preferences,
            "selected_categories": selected_categories,
            "custom_categories": custom_categories,
            "taxonomy_customizations": taxonomy_customizations,
            "model_training_consent": model_training_consent,
            **personalization.model_dump(),
            "versions": memory["schema_versions"],
        }
    )

    return {
        **record,
        "user_id": user_id,
        "profile_version": profile_version,
        "taxonomy_version": taxonomy_version,
        "style_preference_version": style_preference_version,
        "onboarding_completed": onboarding_completed,
        "nickname": nickname,
        "avatar_path": avatar_path,
        "birth_year": birth_year,
        "gender_identity": gender_identity,
        "daily_occasions": daily_occasions,
        "style_preferences": style_preferences,
        "occasion_style_preferences": occasion_style_preferences,
        "selected_categories": selected_categories,
        "custom_categories": custom_categories,
        "taxonomy_customizations": taxonomy_customizations,
        "model_training_consent": model_training_consent,
        **personalization.model_dump(),
        "profile_features": profile_features,
        "default_location_label": record.get("default_location_label"),
        "default_latitude": record.get("default_latitude"),
        "default_longitude": record.get("default_longitude"),
        "temperature_unit": record.get("temperature_unit") or "F",
        "preferences": memory,
    }


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _occasion_style_map(value: Any, occasions: list[str], fallback_styles: list[str]) -> dict[str, list[str]]:
    source = value if isinstance(value, dict) else {}
    result: dict[str, list[str]] = {}
    for occasion in occasions:
        matched = next(
            (styles for label, styles in source.items() if isinstance(label, str) and label.strip().casefold() == occasion.casefold()),
            None,
        )
        result[occasion] = _string_list(matched, fallback_styles) or list(fallback_styles)
    return result


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any, fallback: list[str] | None) -> list[str] | None:
    if not isinstance(value, list):
        return list(fallback) if fallback is not None else None
    cleaned: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in cleaned:
            cleaned.append(item.strip())
    if cleaned:
        return cleaned
    return list(fallback) if fallback is not None else None


def _bool_value(value: Any, fallback: bool) -> bool:
    if value is None:
        return fallback
    return bool(value)


def _record_value(record: dict[str, Any], key: str) -> Any:
    value = record.get(key)
    if value is None:
        return None
    return value
