from app.services.taxonomy import SUBTYPES, normalize_subtype
from app.services.recommendation.rules import recommendation_slot
from app.outfits.service import structurally_valid
from app.models.domain import ClothingItemRecord


def test_athletic_skirt_is_a_bottom_not_a_top():
    assert 'Athletic Skirt' in SUBTYPES['Activewear']
    for name in ['Athletic Skirt','tennis skirt','short athletic skirt']:
        assert normalize_subtype('Activewear',name)=='Athletic Skirt'
    assert recommendation_slot('Activewear','Athletic Skirt')=='Bottoms'
    assert recommendation_slot('Activewear','Workout Top')=='Tops'
    skirt=ClothingItemRecord(user_id='u',category='Activewear',subtype='Athletic Skirt',image_url='https://example.test/skirt')
    top=ClothingItemRecord(user_id='u',category='Tops',subtype='Tank Top',image_url='https://example.test/top')
    trousers=ClothingItemRecord(user_id='u',category='Bottoms',subtype='Trousers',image_url='https://example.test/pants')
    assert structurally_valid([top,skirt])
    assert not structurally_valid([skirt,trousers])


def test_athletic_jacket_remains_outer_layer():
    assert recommendation_slot('Activewear','Athletic Jacket')=='Outerwear'
    assert normalize_subtype('Activewear','athletic skirt')=='Athletic Skirt'
    assert normalize_subtype('Activewear','athletic shorts')=='Athletic Shorts'
