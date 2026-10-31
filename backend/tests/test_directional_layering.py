from app.models.domain import ClothingItemRecord
from app.outfits.service import structurally_valid
from app.outfits.compatibility import core_items
from app.services.recognition_service import ClothingRecognitionService

def garment(category='Tops',subtype='T-shirt',**profile):
    return ClothingItemRecord(user_id='u',image_url='https://example.test/i',category=category,subtype=subtype,recognition_tags={'wearing_profile':profile})

def test_sheer_can_be_inside_or_outside_but_never_alone():
    sheer=garment(subtype='Mesh Top',can_wear_alone=False,requires_inner_layer=False,can_layer_under=True,can_layer_over=True)
    tank=garment(subtype='Tank Top',can_wear_alone=True,can_layer_under=True,can_layer_over=False)
    tee=garment(can_wear_alone=True,can_layer_under=False,can_layer_over=True)
    pants=garment('Bottoms','Jeans')
    assert not structurally_valid([sheer,pants])
    assert structurally_valid([tank,sheer,pants])
    assert structurally_valid([sheer,tee,pants])

def test_directional_requirement_cannot_be_satisfied_by_outer_layer():
    required=garment(subtype='Vest',can_wear_alone=False,requires_inner_layer=True,can_layer_under=True,can_layer_over=True)
    cover=garment(can_wear_alone=True,can_layer_under=False,can_layer_over=True)
    inner=garment(subtype='Tank Top',can_wear_alone=True,can_layer_under=True,can_layer_over=False)
    pants=garment('Bottoms','Jeans')
    assert not structurally_valid([required,cover,pants])
    assert structurally_valid([inner,required,pants])

def test_outer_cover_required_by_core_is_not_optional():
    sheer=garment(subtype='Mesh Top',can_wear_alone=False,requires_inner_layer=False,can_layer_under=True,can_layer_over=False)
    jacket=garment('Outerwear','Jacket',can_layer_over=True,requires_inner_layer=True)
    pants=garment('Bottoms','Jeans')
    assert structurally_valid([sheer,jacket,pants])
    assert jacket in core_items([sheer,jacket,pants])
    opaque=sheer.model_copy(update={'recognition_tags':{'wearing_profile':{'can_wear_alone':True,'can_layer_under':True}}})
    assert jacket not in core_items([opaque,jacket,pants])

def test_no_cardigan_forcing_and_no_layering_obligation():
    service=ClothingRecognitionService()
    analysis=service._normalize_model_payload({'category':'Outerwear','subtype':'Cardigan','wearing_profile':{'can_wear_alone':True,'requires_inner_layer':False}},raw_response={})
    assert analysis.wearing_profile.can_wear_alone is True
    assert analysis.wearing_profile.requires_inner_layer is False
    shirt=garment(subtype='Button-down Shirt',can_wear_alone=True,can_layer_over=True)
    assert structurally_valid([shirt,garment('Bottoms','Jeans')])

def test_mutual_inner_requirements_cannot_form_a_cycle():
    a=garment(can_wear_alone=False,requires_inner_layer=True,can_layer_under=True,can_layer_over=True)
    b=garment(can_wear_alone=False,requires_inner_layer=True,can_layer_under=True,can_layer_over=True)
    assert not structurally_valid([a,b,garment('Bottoms','Jeans')])
