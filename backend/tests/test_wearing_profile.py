import pytest
from pydantic import ValidationError
from app.models.domain import WearingProfile, ClothingItemRecord
from app.models.api import ClothingItemUpdateRequest
from app.services.recognition_service import ClothingRecognitionService
from app.services.item_service import ItemService
from app.outfits.service import revision

PROFILE={'layering_region':None,'lower_layer_role':None,'can_wear_alone':True,'can_layer_over':True,'can_layer_under':True,'requires_inner_layer':False,
         'closure_type':'buttons','wearing_modes':['standalone','inner_layer','outer_layer_open'],
         'evidence':'Opaque shirt with a visible button front.'}

def test_recognition_parses_wearing_profile_and_legacy_is_unknown():
    service=ClothingRecognitionService()
    analysis=service._normalize_model_payload({'category':'Tops','color':'White','wearing_profile':PROFILE},raw_response={})
    assert analysis.wearing_profile.model_dump()==PROFILE
    assert service._normalize_model_payload({'category':'Tops'},raw_response={}).wearing_profile.can_wear_alone is None

@pytest.mark.parametrize('value',[
    {'requires_inner_layer':True,'can_wear_alone':True},
    {'closure_type':'pullover','wearing_modes':['outer_layer_open']},
    {'can_layer_under':False,'wearing_modes':['inner_layer']},
    {'can_wear_alone':'false'},
])
def test_inconsistent_or_non_boolean_capabilities_rejected(value):
    with pytest.raises(ValidationError):WearingProfile.model_validate(value)

def test_manual_label_edit_preserves_profile_and_profile_affects_revision(repository):
    item=repository.add_item(ClothingItemRecord(user_id='u',image_url='https://example.test/i.jpg',category='Tops',color='White',season='Spring',style='Casual',occasion='Everyday',recognition_tags={'wearing_profile':PROFILE}))
    class Embed:
        def create_embedding(self,*args):return [.5]
    saved=ItemService(repository,Embed()).update_item('u',item.id,ClothingItemUpdateRequest(category='Tops',color='Blue',season='Spring',style='Casual',occasion='Everyday'))
    assert saved.wearing_profile==PROFILE
    restored=repository.get_item(item.id,'u')
    assert restored.wearing_profile==PROFILE
    old=restored.model_copy(update={'recognition_tags':{}})
    assert old.wearing_profile['can_wear_alone'] is None
    assert revision(restored)!=revision(old)
    # Derived accessor is not serialized into a nonexistent SQL column.
    assert 'wearing_profile' not in restored.model_dump()

def test_pipeline_persists_profile_in_item_and_machine_record(repository):
    import json
    from app.models.domain import ClothingAnalysis, RecognitionJobRecord
    from app.services.recognition_pipeline import RecognitionPipeline
    item=repository.add_item(ClothingItemRecord(user_id='u',category='Tops',image_url='https://example.test/i.jpg',image_path='i.jpg'))
    job=repository.create_recognition_job(RecognitionJobRecord(user_id='u',clothing_item_id=item.id,filename='i.jpg',image_url=item.image_url,image_path=item.image_path))
    class Model:
        def analyze(self,*a,**kw):return ClothingAnalysis(category='Tops',wearing_profile=PROFILE,source='OpenAI Vision')
    class Embed:
        def create_embedding(self,*a):return [.5]
    class Storage:
        def signed_image_url(self,*a,**kw):return item.image_url
    RecognitionPipeline(repository,Model(),Embed(),Storage()).process_job(job)
    assert repository.get_item(item.id,'u').wearing_profile==PROFILE
    records=json.loads(repository.recognition_records_path.read_text())
    assert records[-1]['normalized_payload']['wearing_profile']==PROFILE
