import pytest
from app.services.recognition_service import ClothingRecognitionService
from app.services.taxonomy import constrain_category, normalize_subtype


@pytest.mark.parametrize('category,subtype,expected', [
    ('Tops', 'Workout Top', 'Workout Top'),
    ('Tops', 'yoga top', 'Workout Top'),
    ('Tops', 'athletic tank', 'Workout Top'),
    ('Tops', 'running shirt', 'Workout Top'),
    ('Tops', 'Sports Bra', 'Sports Bra'),
    ('Outerwear', 'Athletic Jacket', 'Athletic Jacket'),
    ('Bottoms', 'wide-leg yoga pants', 'Yoga Pants'),
    ('Bottoms', 'Workout Leggings', 'Workout Leggings'),
])
def test_conflicting_category_preserves_explicit_athletic_type(category, subtype, expected):
    result = ClothingRecognitionService()._normalize_model_payload(
        {'category': category, 'subtype': subtype}, raw_response={})
    assert result.category == 'Activewear'
    assert result.subtype == expected
    assert result.raw_category == category
    assert result.raw_subtype == subtype


@pytest.mark.parametrize('category,subtype', [
    ('Tops', 'T-shirt'), ('Tops', 'Tank Top'), ('Tops', 'Hoodie'),
    ('Bottoms', 'Wide-leg Pants'), ('Bottoms', 'Joggers'),
])
def test_generic_silhouettes_are_not_forced_into_activewear(category, subtype):
    assert constrain_category(category, subtype) == category


def test_respects_disabled_activewear_and_does_not_map_yoga_top_to_pants():
    assert constrain_category('Tops', 'Workout Top', ['Tops', 'Bottoms']) == 'Tops'
    assert normalize_subtype('Activewear', 'yoga top') == 'Workout Top'
    assert normalize_subtype('Activewear', 'yoga') is None
