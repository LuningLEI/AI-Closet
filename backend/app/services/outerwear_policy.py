"""Non-negotiable product rules for outerwear used as a standalone top."""
from __future__ import annotations

from app.models.domain import WearingProfile


NON_STANDALONE_OUTERWEAR_SUBTYPES = frozenset({
    "jacket",
    "coat",
    "blazer",
    "trench coat",
    "puffer",
})


def is_non_standalone_outerwear(subtype: str | None) -> bool:
    return (subtype or "").strip().casefold() in NON_STANDALONE_OUTERWEAR_SUBTYPES


def enforce_outerwear_profile(category: str, subtype: str | None,
                              profile: WearingProfile) -> WearingProfile:
    """Override model/user claims that contradict the product's hard taxonomy."""
    if category != "Outerwear" or not is_non_standalone_outerwear(subtype):
        return profile
    data = profile.model_dump()
    data.update(
        layering_region="upper_body",
        can_wear_alone=False,
        can_layer_over=True,
        requires_inner_layer=True,
        wearing_modes=[
            mode for mode in data.get("wearing_modes", [])
            if mode != "standalone"
        ],
        evidence="Product policy: this outerwear subtype requires an upper-body inner layer.",
    )
    if "outer_layer_closed" not in data["wearing_modes"]:
        data["wearing_modes"].append("outer_layer_closed")
    return WearingProfile.model_validate(data)


def outerwear_can_replace_top(item) -> bool:
    """Only a user/model-confirmed Cardigan may fill the otherwise missing Top slot."""
    profile = item.wearing_profile
    return (
        (item.subtype or "").strip().casefold() == "cardigan"
        and profile.get("can_wear_alone") is True
        and profile.get("requires_inner_layer") is not True
    )
