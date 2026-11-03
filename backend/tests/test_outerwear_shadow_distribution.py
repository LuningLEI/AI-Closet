import pytest

from app.models.domain import ClothingItemRecord
from app.outfits.outerwear_distribution import OuterwearShadowConfig, outerwear_distribution


def item(item_id, category, subtype, *, fit=None, material=None, sleeve="Long Sleeve", profile=None):
    return ClothingItemRecord(
        id=item_id,
        user_id="user-1",
        image_url=f"{item_id}.jpg",
        category=category,
        subtype=subtype,
        fit=fit,
        material=material,
        sleeve_length=sleeve,
        recognition_tags={"wearing_profile": profile or {}},
        occasion="Everyday",
        style="Casual",
    )


def test_distribution_penalizes_fitted_cardigan_over_bulky_top_and_sums_to_one():
    sweater = item("sweater", "Tops", "Sweater", fit="Oversized", material="Chunky wool",
                   profile={"can_layer_under": True})
    cardigan = item("cardigan", "Outerwear", "Cardigan", fit="Fitted",
                    profile={"can_layer_over": True})
    coat = item("coat", "Outerwear", "Coat", fit="Relaxed",
                profile={"can_layer_over": True})

    rows = outerwear_distribution(
        [sweater],
        [cardigan, coat],
        config=OuterwearShadowConfig(temperature_f=50, softmax_temperature=0.75),
        seed="fixed",
    )
    by_id = {row.outerwear_id: row for row in rows}

    assert by_id["cardigan"].fit_score < by_id["coat"].fit_score
    assert by_id["cardigan"].probability < by_id["coat"].probability
    assert sum(row.probability for row in rows) == pytest.approx(1.0)
    assert sum(row.shadow_selected for row in rows) == 1


def test_existing_layer_capability_rule_masks_impossible_candidate():
    top = item("top", "Tops", "T-shirt", profile={"can_layer_under": False})
    jacket = item("jacket", "Outerwear", "Jacket", profile={"can_layer_over": True})

    rows = outerwear_distribution([top], [jacket], seed="fixed")
    jacket_row = next(row for row in rows if row.outerwear_id == "jacket")

    assert jacket_row.masked is True
    assert jacket_row.probability == 0
    assert "production_layer_capability_rule" in jacket_row.mask_reasons


def test_none_option_gains_probability_in_warm_weather():
    top = item("top", "Tops", "T-shirt", profile={"can_layer_under": True})
    coat = item("coat", "Outerwear", "Puffer", profile={"can_layer_over": True})

    cool = outerwear_distribution([top], [coat], config=OuterwearShadowConfig(temperature_f=40), seed="one")
    warm = outerwear_distribution([top], [coat], config=OuterwearShadowConfig(temperature_f=85), seed="one")
    cool_none = next(row for row in cool if row.outerwear_id is None)
    warm_none = next(row for row in warm if row.outerwear_id is None)

    assert warm_none.probability > cool_none.probability
