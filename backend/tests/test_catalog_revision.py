import pytest
from pydantic import ValidationError
from app.services.taxonomy import SUBTYPES, OCCASIONS, constrain_category, normalize_subtype
from app.services.recognition_service import ClothingRecognitionService
from app.services.occasion_support import effective_occasion
from app.services.occasion_thresholds import validate_thresholds
from app.models.domain import ClothingItemRecord, ColorTone
from app.outfits.service import structurally_valid
from app.services.recommendation.rules import layers_compatible

def test_catalog_merges():
    assert 'Vacation' not in OCCASIONS
    assert 'Crop Top' not in SUBTYPES['Tops'] and 'Cardigan' not in SUBTYPES['Tops']
    assert SUBTYPES['Dresses']==['Unknown','Slip Dress','Shirt Dress','Wrap Dress','Sweater Dress','T-shirt Dress','A-line Dress']
    for category,old,new in [('Jumpsuits','Playsuit','Romper'),('Sets','Matching Set','Two-piece Set'),('Sets','Co-ord Set','Two-piece Set'),('Shoes','Pumps','Heels')]:
        assert old not in SUBTYPES[category]
        assert normalize_subtype(category,old)==new
    assert constrain_category('Tops','Cardigan')=='Outerwear'

def test_lengths_and_travel_merge_keep_information():
    service=ClothingRecognitionService()
    for subtype,length in [('Crop Top','Cropped'),('Mini Dress','Thigh'),('Midi Dress','Midi'),('Maxi Dress','Maxi')]:
        analysis=service._normalize_model_payload({'category':'Tops' if subtype=='Crop Top' else 'Dresses','subtype':subtype},raw_response={})
        assert analysis.length==length and analysis.subtype is None
    scores=service._normalize_occasion_scores([{'occasion':'Vacation','score':.9},{'occasion':'Travel','score':.7}])
    assert len(scores)==1 and scores[0].occasion=='Travel' and scores[0].score==.9
    item=ClothingItemRecord(user_id='u',image_url='x',category='Tops',occasion='Vacation, Travel')
    assert effective_occasion(item)=='Travel'
    assert validate_thresholds({'Vacation':.9,'Travel':.8})=={'Travel':.8}

def test_color_tones_and_cardigan_requirements():
    service=ClothingRecognitionService()
    analysis=service._normalize_model_payload({'category':'Tops','subtype':'Cardigan','color':'Pink','color_tones':[{'color':'Pink','hue':335,'saturation':.25,'lightness':.8}], 'wearing_profile':{'can_wear_alone':False,'can_layer_over':True,'requires_inner_layer':True}},raw_response={})
    assert analysis.category=='Outerwear'
    assert analysis.color_tones[0].lightness==.8
    assert analysis.wearing_profile.requires_inner_layer is True
    assert analysis.wearing_profile.can_wear_alone is False
    with pytest.raises(ValidationError):ColorTone(color='Pink',lightness=1.2)
    inner=ClothingItemRecord(user_id='u',image_url='x',category='Activewear',subtype='Sports Bra',recognition_tags={'wearing_profile':{'can_layer_under':True}})
    outer=ClothingItemRecord(user_id='u',image_url='x',category='Outerwear',subtype='Cardigan',recognition_tags=analysis.model_dump())
    bottom=ClothingItemRecord(user_id='u',image_url='x',category='Bottoms')
    assert layers_compatible(inner,outer)
    assert structurally_valid([inner,outer,bottom])
    unknown=inner.model_copy(update={'recognition_tags':{}})
    # Unknown remains a retrieval candidate, but cannot satisfy an explicit requirement.
    assert not structurally_valid([unknown,outer,bottom])
    changed=outer.model_copy(update={'color':'Blue'})
    assert changed.color_tones==[]
