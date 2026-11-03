from app.models.domain import ClothingItemRecord
from app.services.layering_fit import assess_layering_pair, assess_outfit_layering


def garment(
    item_id: str,
    category: str,
    subtype: str,
    *,
    fit: str | None = None,
    material: str | None = None,
    summary: str = "",
    **wearing_profile,
) -> ClothingItemRecord:
    return ClothingItemRecord(
        id=item_id,
        user_id="00000000-0000-4000-8000-0000000000a1",
        image_url=f"https://example.test/{item_id}.jpg",
        category=category,
        subtype=subtype,
        fit=fit,
        material=material,
        recognition_summary=summary,
        recognition_tags={"wearing_profile": wearing_profile},
    )


def test_hoodie_under_regular_denim_jacket_is_a_hard_failure() -> None:
    hoodie = garment("hoodie", "Tops", "Hoodie", can_layer_under=True)
    jacket = garment(
        "denim-jacket",
        "Outerwear",
        "Denim Jacket",
        material="denim",
        can_layer_over=True,
    )

    assessment = assess_layering_pair(hoodie, jacket)

    assert assessment.hard_failure is True
    assert assessment.score < -1.5
    assert any("jacket" in reason for reason in assessment.reasons)


def test_relaxed_denim_jacket_can_fit_a_hoodie() -> None:
    hoodie = garment("hoodie", "Tops", "Hoodie", can_layer_under=True)
    jacket = garment(
        "relaxed-denim-jacket",
        "Outerwear",
        "Denim Jacket",
        fit="Relaxed",
        material="denim",
        can_layer_over=True,
    )

    assert assess_layering_pair(hoodie, jacket).hard_failure is False


def test_fitted_cardigan_and_vest_reject_bulky_inner_layers() -> None:
    hoodie = garment("hoodie", "Tops", "Hoodie", can_layer_under=True)
    chunky_sweater = garment(
        "sweater",
        "Tops",
        "Sweater",
        fit="Oversized",
        summary="chunky cable knit",
        can_layer_under=True,
    )
    cardigan = garment(
        "cardigan",
        "Outerwear",
        "Cardigan",
        fit="Fitted",
        can_layer_over=True,
    )
    vest = garment("vest", "Outerwear", "Vest", fit="Fitted", can_layer_over=True)

    assert assess_layering_pair(hoodie, cardigan).hard_failure is True
    assert assess_layering_pair(chunky_sweater, vest).hard_failure is True


def test_light_inner_and_roomy_outerwear_remain_valid() -> None:
    tank = garment("tank", "Tops", "Tank Top", can_layer_under=True)
    cardigan = garment(
        "cardigan",
        "Outerwear",
        "Cardigan",
        fit="Relaxed",
        material="knit",
        can_layer_over=True,
    )
    hoodie = garment("hoodie", "Tops", "Hoodie", can_layer_under=True)
    coat = garment(
        "coat",
        "Outerwear",
        "Coat",
        fit="Relaxed",
        can_layer_over=True,
    )

    assert assess_layering_pair(tank, cardigan).hard_failure is False
    assert assess_layering_pair(hoodie, coat).score > assess_layering_pair(hoodie, cardigan).score


def test_explicit_recognition_capacity_overrides_subtype_fallback() -> None:
    hoodie = garment(
        "hoodie",
        "Tops",
        "Hoodie",
        can_layer_under=True,
        layering_bulk="high",
        hood_volume="high",
    )
    roomy_vest = garment(
        "roomy-vest",
        "Outerwear",
        "Vest",
        can_layer_over=True,
        outer_capacity="high",
        material_stiffness="soft",
    )

    assert assess_layering_pair(hoodie, roomy_vest).hard_failure is False


def test_outfit_assessment_returns_the_weakest_upper_body_pair() -> None:
    shirt = garment("shirt", "Tops", "Button-down Shirt", can_layer_under=True)
    hoodie = garment("hoodie", "Tops", "Hoodie", can_layer_under=True)
    fitted_vest = garment(
        "vest",
        "Outerwear",
        "Vest",
        fit="Fitted",
        can_layer_over=True,
    )
    pants = garment("pants", "Bottoms", "Trousers")

    assessment = assess_outfit_layering([shirt, hoodie, fitted_vest, pants])

    assert assessment is not None
    assert assessment.hard_failure is True
    assert assessment.inner_bulk == "high"
