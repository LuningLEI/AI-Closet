from app.services.taxonomy import SUBTYPES,constrain_category,normalize_subtype
from app.services.recommendation.rules import recommendation_slot


def test_leggings_are_only_activewear_and_still_bottoms_for_outfits():
    assert 'Leggings' not in SUBTYPES['Bottoms']
    assert 'Workout Leggings' in SUBTYPES['Activewear']
    for label in ['Leggings','Workout Leggings']:
        category=constrain_category('Bottoms',label)
        assert category=='Activewear'
        assert normalize_subtype(category,label)=='Workout Leggings'
    assert recommendation_slot('Activewear','Workout Leggings')=='Bottoms'
    assert constrain_category('Bottoms','Trousers')=='Bottoms'
    assert constrain_category('Bottoms','Leggings',['Bottoms','Tops'])=='Bottoms'


def test_yoga_pants_use_activewear_without_reclassifying_ordinary_trousers():
    for label in ['Yoga Pants', 'yoga leggings', 'wide-leg yoga pants', 'flared yoga trousers']:
        category = constrain_category('Bottoms', label)
        assert category == 'Activewear'
        assert normalize_subtype(category, label) == 'Yoga Pants'
    assert recommendation_slot('Activewear', 'Yoga Pants') == 'Bottoms'
    assert constrain_category('Bottoms', 'Wide-leg Pants') == 'Bottoms'
    assert constrain_category('Bottoms', 'Joggers') == 'Bottoms'
    assert constrain_category('Bottoms', 'Yoga Pants', ['Bottoms', 'Tops']) == 'Bottoms'
