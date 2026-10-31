from app.services.taxonomy import SUBTYPES,normalize_subtype,constrain_category
from app.services.recommendation.rules import recommendation_slot
from app.outfits.service import structurally_valid
from app.models.domain import ClothingItemRecord


def test_ski_types_and_roles():
    for label,role in [('Ski Jacket','Outerwear'),('Ski Pants','Bottoms'),('Ski Suit','FullBody')]:
        assert label in SUBTYPES['Activewear']
        assert constrain_category('Outerwear',label)=='Activewear'
        assert normalize_subtype('Activewear',label.lower())==label
        assert recommendation_slot('Activewear',label)==role
    assert constrain_category('Bottoms','Mini Skirt')=='Bottoms'
    assert normalize_subtype('Activewear','Athletic Skirt')=='Athletic Skirt'
    suit=ClothingItemRecord(user_id='u',category='Activewear',subtype='Ski Suit',image_url='https://example.test/suit')
    pants=ClothingItemRecord(user_id='u',category='Activewear',subtype='Ski Pants',image_url='https://example.test/pants')
    assert structurally_valid([suit])
    assert not structurally_valid([suit,pants])
