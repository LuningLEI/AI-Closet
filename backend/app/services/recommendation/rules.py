from __future__ import annotations

from datetime import datetime, timezone

from app.core.constants import (
    ACCESSORY_CATEGORIES,
    COLD_WEATHER_F,
    COOL_WEATHER_F,
    FULL_BODY_CATEGORIES,
    LayeringRole,
    MODERATE_WEATHER_F,
    TOP_COMPATIBLE_CATEGORIES,
)
from app.models.domain import ClothingItemRecord


def recommendation_slot(category: str) -> str:
    if category in FULL_BODY_CATEGORIES:
        return LayeringRole.FULL_BODY
    if category in ACCESSORY_CATEGORIES:
        return LayeringRole.ACCESSORIES
    if category in TOP_COMPATIBLE_CATEGORIES:
        return "Tops"
    return category


def top_layer(item: ClothingItemRecord) -> str:
    descriptor = f"{item.category} {item.subtype or ''} {item.recognition_summary or ''}".lower()
    if any(word in descriptor for word in ["tank", "camisole", "cami", "t-shirt", "tee", "bodysuit", "sports bra", "bra"]):
        return LayeringRole.BASE_TOP
    if any(word in descriptor for word in ["hoodie", "cardigan", "pullover", "sweater", "vest"]):
        return LayeringRole.MID_LAYER
    return LayeringRole.TOP


def layers_compatible(inner: ClothingItemRecord, outer: ClothingItemRecord) -> bool:
    inner_layer = top_layer(inner)
    outer_layer = top_layer(outer)
    if inner_layer == LayeringRole.MID_LAYER:
        return False
    if inner_layer == outer_layer:
        return False
    return True


def allowed_seasons(temperature_f: float) -> set[str]:
    if temperature_f < COLD_WEATHER_F:
        return {"winter", "fall", "all-season"}
    if temperature_f < COOL_WEATHER_F:
        return {"spring", "fall", "all-season"}
    if temperature_f < MODERATE_WEATHER_F:
        return {"spring", "summer", "all-season"}
    return {"summer", "all-season"}


def profile_memory_text(preferences: dict | None) -> str:
    if not isinstance(preferences, dict):
        return ""
    profile = preferences.get("profile", {})
    if not isinstance(profile, dict):
        return ""

    birth_year = profile.get("birth_year")
    age_text = ""
    if isinstance(birth_year, int):
        age_text = f"estimated current age: {datetime.now(timezone.utc).year - birth_year}"

    daily_occasions = profile.get("daily_occasions") if isinstance(profile.get("daily_occasions"), list) else []
    style_preferences = profile.get("style_preferences") if isinstance(profile.get("style_preferences"), list) else []
    return " ".join(
        value
        for value in [
            "long term user profile:",
            age_text,
            f"gender identity: {profile.get('gender_identity') or 'unspecified'}",
            f"daily occasions: {', '.join(daily_occasions)}",
            f"preferred styles: {', '.join(style_preferences)}",
        ]
        if value
    )
