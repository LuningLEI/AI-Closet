import pytest

from app.models.domain import ClothingItemRecord
from app.outfits.service import structural_rejection_codes
from app.services.recognition_service import ClothingRecognitionService


def garment(category, subtype, profile):
    return ClothingItemRecord(
        user_id="u", image_url="https://example.test/item.jpg",
        category=category, subtype=subtype,
        recognition_tags={"wearing_profile": profile},
    )


@pytest.mark.parametrize("subtype", ["Jacket", "Coat", "Blazer", "Trench Coat", "Puffer"])
def test_non_standalone_outerwear_never_replaces_top(subtype):
    bottom = garment("Bottoms", "Trousers", {"can_wear_alone": True})
    outerwear = garment("Outerwear", subtype, {
        "can_wear_alone": True,
        "can_layer_over": True,
        "requires_inner_layer": False,
    })

    assert "missing_top" in structural_rejection_codes([bottom, outerwear])


def test_only_confirmed_cardigan_may_replace_top():
    bottom = garment("Bottoms", "Trousers", {"can_wear_alone": True})
    cardigan = garment("Outerwear", "Cardigan", {
        "can_wear_alone": True,
        "can_layer_over": True,
        "requires_inner_layer": False,
    })

    assert "missing_top" not in structural_rejection_codes([bottom, cardigan])


@pytest.mark.parametrize("subtype", ["Jacket", "Coat", "Blazer", "Trench Coat", "Puffer"])
def test_recognition_normalization_enforces_outerwear_policy(subtype):
    analysis = ClothingRecognitionService()._normalize_model_payload({
        "category": "Outerwear",
        "subtype": subtype,
        "wearing_profile": {
            "can_wear_alone": True,
            "can_layer_over": True,
            "requires_inner_layer": False,
            "wearing_modes": ["standalone", "outer_layer_closed"],
        },
    }, raw_response={})

    assert analysis.wearing_profile.can_wear_alone is False
    assert analysis.wearing_profile.requires_inner_layer is True
    assert "standalone" not in analysis.wearing_profile.wearing_modes
