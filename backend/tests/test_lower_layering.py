from app.models.domain import ClothingItemRecord
from app.outfits.service import structurally_valid
from app.outfits.compatibility import core_items, optional_layer_ids
from app.outfits.catalog import exclusion_reason
from app.outfits.config import load_config

def item(category,subtype,**profile):
    return ClothingItemRecord(user_id='u',image_url='https://example.test/i',category=category,subtype=subtype,recognition_tags={'wearing_profile':profile})

def test_leggings_and_outer_skirt_survive_candidate_and_core_checks():
    legs=item('Activewear','Workout Leggings',layering_region='lower_body',lower_layer_role='base',can_layer_under=True,can_wear_alone=True)
    skirt=item('Bottoms','Midi Skirt',layering_region='lower_body',lower_layer_role='outer',can_layer_over=True,can_wear_alone=True)
    sweater=item('Tops','Sweater',can_wear_alone=True)
    assert exclusion_reason(legs,skirt,load_config()) is None
    assert exclusion_reason(skirt,legs,load_config()) is None
    assert structurally_valid([sweater,legs,skirt])
    assert len(core_items([sweater,legs,skirt]))==2
    assert len(optional_layer_ids([sweater,legs,skirt]))==1
    assert structurally_valid([sweater,legs])

def test_unknown_or_incompatible_two_bottoms_rejected():
    top=item('Tops','T-shirt')
    for b in [item('Bottoms','Jeans'),item('Bottoms','Shorts',lower_layer_role='outer',can_layer_over=False)]:
        base=item('Activewear','Workout Leggings',lower_layer_role='base',can_layer_under=True)
        assert not structurally_valid([top,base,b])
        assert exclusion_reason(base,b,load_config()) is not None
    a=item('Bottoms','Trousers',lower_layer_role='outer',can_layer_over=True)
    b=item('Bottoms','Trousers',lower_layer_role='outer',can_layer_over=True)
    assert not structurally_valid([top,a,b])

def test_lower_requirements_cannot_be_satisfied_by_upper_top():
    sheer=item('Bottoms','Shorts',lower_layer_role='outer',can_layer_over=True,can_wear_alone=False,requires_inner_layer=True)
    top=item('Tops','T-shirt',can_layer_under=True)
    base=item('Activewear','Workout Leggings',lower_layer_role='base',can_layer_under=True,can_wear_alone=True)
    assert not structurally_valid([top,sheer])
    assert structurally_valid([top,base,sheer])

def test_explicit_dress_cover_and_no_arbitrary_dress_trousers():
    dress=item('Dresses','Sweater Dress',lower_layer_role='outer',can_layer_over=True,can_wear_alone=True)
    base=item('Activewear','Workout Leggings',lower_layer_role='base',can_layer_under=True,can_wear_alone=False)
    assert structurally_valid([dress,base])
    assert exclusion_reason(dress,base,load_config()) is None
    assert not structurally_valid([dress,item('Bottoms','Jeans')])


def test_required_lower_layers_remain_core():
    top=item('Tops','T-shirt',can_wear_alone=True)
    base=item('Activewear','Workout Leggings',lower_layer_role='base',can_layer_under=True,can_wear_alone=False)
    outer=item('Bottoms','Midi Skirt',lower_layer_role='outer',can_layer_over=True,requires_inner_layer=True,can_wear_alone=False)
    assert structurally_valid([top,base,outer])
    assert len(core_items([top,base,outer]))==3
    assert optional_layer_ids([top,base,outer])==[]


def test_yoga_silhouette_controls_lower_layering():
    from app.services.layering_support import lower_layer_pair
    yoga=item('Activewear','Yoga Pants',lower_layer_role='base',can_layer_under=True,can_wear_alone=True)
    skirt=item('Bottoms','Mini Skirt',lower_layer_role='outer',can_layer_over=True,can_wear_alone=True)
    yoga.fit='Skinny'
    assert lower_layer_pair(yoga,skirt)
    for fit in ['Wide-leg', 'Flared']:
        yoga.fit=fit
        assert not lower_layer_pair(yoga,skirt)
        assert structurally_valid([item('Tops','Workout Top'),yoga])
