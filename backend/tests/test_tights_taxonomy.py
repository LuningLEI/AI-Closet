from app.services.taxonomy import SUBTYPES,normalize_subtype
from app.services.recommendation.rules import recommendation_slot
from app.outfits.service import structurally_valid
from app.models.domain import ClothingItemRecord


def test_tights_are_an_optional_layer_not_a_core_garment():
    assert 'Tights' in SUBTYPES['Intimates']
    for name in ['Tights','sheer tights','Pantyhose']:
        assert normalize_subtype('Intimates',name)=='Tights'
    assert recommendation_slot('Intimates','Tights')=='Accessories'
    def item(category,subtype):
        return ClothingItemRecord(user_id='u',category=category,subtype=subtype,image_url='https://example.test/image')
    tights=item('Intimates','Tights');top=item('Tops','Blouse');skirt=item('Bottoms','Mini Skirt')
    assert structurally_valid([top,skirt,tights])
    assert not structurally_valid([top,tights])
    assert not structurally_valid([skirt,tights])


def test_tights_require_skirt_shorts_or_dress_in_library_and_recommendations():
    from app.services.recommendation.candidates import CandidateGenerator
    from app.services.recommendation.models import Candidate
    def item(category, subtype):
        return ClothingItemRecord(user_id='u',category=category,subtype=subtype,image_url='https://example.test/image')
    tights=item('Intimates','Tights');top=item('Tops','Blouse')
    generator=CandidateGenerator()
    for category, subtype, allowed in [('Bottoms','Shorts',True),('Bottoms','Pencil Skirt',True),('Activewear','Athletic Skirt',True),('Bottoms','Trousers',False),('Activewear','Workout Leggings',False)]:
        bottom=item(category,subtype)
        assert structurally_valid([top,bottom,tights]) is allowed
        results=[]
        generator._append_unique(results,set(),Candidate(top=top,bottom=bottom,accessory=tights))
        assert bool(results) is allowed
    assert structurally_valid([item('Dresses','Mini Dress'),tights])
    assert not structurally_valid([item('Jumpsuits','Jumpsuit'),tights])
    results=[]
    generator._append_unique(results,set(),Candidate(accessory=tights))
    assert not results


def test_skirt_does_not_rescue_tights_with_trousers_or_leggings():
    from app.outfits.catalog import exclusion_reason
    from app.outfits.config import load_config
    def item(c,s,profile=None):
        return ClothingItemRecord(user_id='u',category=c,subtype=s,image_url='x',recognition_tags={'wearing_profile':profile or {}})
    tights=item('Intimates','Tights',{'can_wear_alone':False,'can_layer_under':True,'lower_layer_role':'base'})
    top=item('Tops','Sweater');skirt=item('Bottoms','Midi Skirt')
    for category,subtype in [('Bottoms','Jeans'),('Bottoms','Wide-leg Pants'),('Activewear','Workout Leggings')]:
        pants=item(category,subtype)
        assert not structurally_valid([top,skirt,pants,tights])
        assert exclusion_reason(tights,pants,load_config()) is not None
        assert exclusion_reason(pants,tights,load_config()) is not None
    assert structurally_valid([top,skirt,tights])
    blocked=skirt.model_copy(update={'recognition_tags':{'wearing_profile':{'can_layer_over':False}}})
    assert not structurally_valid([top,blocked,tights])


def test_required_hosiery_remains_in_core():
    from app.outfits.compatibility import core_items
    top=ClothingItemRecord(user_id='u',category='Tops',image_url='x')
    skirt=ClothingItemRecord(user_id='u',category='Bottoms',subtype='Midi Skirt',image_url='x',recognition_tags={'wearing_profile':{'can_wear_alone':False,'requires_inner_layer':True,'can_layer_over':True}})
    tights=ClothingItemRecord(user_id='u',category='Intimates',subtype='Tights',image_url='x',recognition_tags={'wearing_profile':{'can_wear_alone':False,'can_layer_under':True}})
    assert structurally_valid([top,skirt,tights])
    assert tights in core_items([top,skirt,tights])
