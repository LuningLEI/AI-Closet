from app.services.preference_schema import normalize_preference_updates
from app.services.taxonomy import merge_preferences,user_taxonomy
from app.services.recognition_service import ClothingRecognitionService


def customized():
    return {
        'subtypes':{'Tops':['Unknown','Corset Top']},
        'colors':['Unknown','Black','Dusty Rose'],
        'styles':['Casual','Avant-garde'],
        'occasions':['Everyday','Concert'],
        'seasons':['Warm Weather','Cold Weather'],
        'lengths':['Cropped','Longline'],
        'sleeve_lengths':['Sleeveless','Bell Sleeve'],
    }


def test_custom_taxonomy_round_trips_in_preferences_and_resolves_catalog():
    row=normalize_preference_updates('user-1',None,{
        'selected_categories':['Tops'],'custom_categories':[],
        'taxonomy_customizations':customized(),
    })
    assert row['taxonomy_customizations']==customized()
    taxonomy=user_taxonomy(row['preferences'])
    assert taxonomy['subtypes']['Tops']==['Unknown','Corset Top']
    assert taxonomy['colors']==['Unknown','Black','Dusty Rose']
    assert taxonomy['occasions']==['Everyday','Concert']


def test_recognition_accepts_exact_user_enum_values():
    service=ClothingRecognitionService()
    taxonomy={'categories':['Tops'],**customized()}
    analysis=service._normalize_model_payload({
        'category':'Tops','subtype':'Corset Top','color':'Dusty Rose','style':'Avant-garde',
        'seasons':['Warm Weather'],'occasion_scores':[{'occasion':'Concert','score':.9}],
        'length':'Longline','sleeve_length':'Bell Sleeve',
    },{},allowed_categories=['Tops'],allowed_taxonomy=taxonomy)
    assert (analysis.category,analysis.subtype)==('Tops','Corset Top')
    assert analysis.color=='Dusty Rose' and analysis.style=='Avant-garde'
    assert analysis.occasion=='Concert' and analysis.seasons==['Warm Weather']
    assert analysis.length=='Longline' and analysis.sleeve_length=='Bell Sleeve'


def test_invalid_and_oversized_custom_values_are_sanitized():
    preferences=merge_preferences({'taxonomy':{
        'selected_categories':['Tops'],
        'customizations':{'colors':['Unknown','',123,'x'*61,'Blue','Blue'],'ignored':['x']}
    }})
    assert user_taxonomy(preferences)['colors']==['Unknown','Blue']
