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
from app.services.occasion_support import effective_occasion
from app.services.layering_fit import assess_layering_pair


def recommendation_slot(category: str, subtype: str | None = None) -> str:
    if subtype == "Cardigan":
        return "Outerwear"
    if category == "Intimates" and subtype == "Tights":
        return LayeringRole.ACCESSORIES
    if category == "Activewear" and subtype in {"Athletic Jacket", "Ski Jacket"}:
        return "Outerwear"
    if category == "Activewear" and subtype in {"Athletic Skirt", "Athletic Shorts", "Workout Leggings", "Yoga Pants", "Track Pants", "Ski Pants"}:
        return "Bottoms"
    if category == "Activewear" and subtype == "Ski Suit":
        return LayeringRole.FULL_BODY
    if category in FULL_BODY_CATEGORIES:
        return LayeringRole.FULL_BODY
    if category in ACCESSORY_CATEGORIES:
        return LayeringRole.ACCESSORIES
    if category in TOP_COMPATIBLE_CATEGORIES:
        return "Tops"
    return category


def is_tights(item):
    return item.category == 'Intimates' and (item.subtype or '').lower() in {'tights','pantyhose'}


def tights_cover(item):
    return item.category == 'Dresses' or (recommendation_slot(item.category,item.subtype)=='Bottoms'
        and any(word in (item.subtype or '').lower() for word in ('skirt','shorts')))


def tights_layering_valid(items: list[ClothingItemRecord]) -> bool:
    hosiery=[i for i in items if is_tights(i)]
    if not hosiery:return True
    if len(hosiery)>1:return False
    # Even adding a skirt must not rescue tights worn with trousers or leggings.
    lower=[i for i in items if recommendation_slot(i.category,i.subtype) in {'Bottoms','FullBody'}]
    if not lower or any(not tights_cover(i) for i in lower):return False
    return hosiery[0].wearing_profile['can_layer_under'] is not False and any(
        i.wearing_profile['can_layer_over'] is not False for i in lower)


def top_layer(item: ClothingItemRecord) -> str:
    descriptor = f"{item.category} {item.subtype or ''} {item.recognition_summary or ''}".lower()
    if any(word in descriptor for word in ["tube top", "strapless top", "tank", "camisole", "cami", "t-shirt", "tee", "bodysuit", "sports bra", "bra"]):
        return LayeringRole.BASE_TOP
    if any(word in descriptor for word in ["hoodie", "cardigan", "pullover", "sweater", "vest"]):
        return LayeringRole.MID_LAYER
    return LayeringRole.TOP


def layers_compatible(inner: ClothingItemRecord, outer: ClothingItemRecord) -> bool:
    if inner.wearing_profile['can_layer_under'] is False or outer.wearing_profile['can_layer_over'] is False:
        return False
    if assess_layering_pair(inner, outer).hard_failure:
        return False
    if inner.wearing_profile['can_layer_under'] is True and outer.wearing_profile['can_layer_over'] is True:
        return True
    if recommendation_slot(outer.category, outer.subtype) == "Outerwear" and recommendation_slot(inner.category, inner.subtype) != "Outerwear":
        return True  # Legacy unknown profiles remain candidates for image review.
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


def occasion_tokens(value: str) -> set[str]:
    """Normalize the comma-separated multi-select value stored on an item."""
    return {token.strip().lower() for token in value.split(",") if token.strip()}


def item_occasion_tokens(item: ClothingItemRecord) -> set[str]:
    return occasion_tokens(effective_occasion(item))

def profile_memory_text(preferences: dict | None, occasion: str | None = None) -> str:
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
    from app.services.taxonomy import preferred_styles_for_occasion
    style_preferences = preferred_styles_for_occasion(preferences, occasion)
    return " ".join(
        value
        for value in [
            "long term user profile:",
            age_text,
            f"gender identity: {profile.get('gender_identity') or 'unspecified'}",
            f"daily occasions: {', '.join(daily_occasions)}",
            f"preferred styles for {occasion or 'all occasions'}: {', '.join(style_preferences)}",
        ]
        if value
    )
