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
PROFILE_WITH_CAPACITY = PROFILE | {
    'layering_bulk': None,
    'outer_capacity': None,
    'material_stiffness': None,
    'hood_volume': None,
    'sleeve_volume': None,
}

def test_recognition_parses_wearing_profile_and_legacy_is_unknown():
    service=ClothingRecognitionService()
    analysis=service._normalize_model_payload({'category':'Tops','color':'White','wearing_profile':PROFILE},raw_response={})
    assert analysis.wearing_profile.model_dump()==PROFILE_WITH_CAPACITY
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


def test_taxonomy_change_replaces_stale_layering_profile(repository):
    cardigan = repository.add_item(ClothingItemRecord(
        user_id='u', image_url='https://example.test/cardigan.jpg',
        category='Outerwear', subtype='Cardigan', color='Green', season='Fall',
        style='Casual', occasion='Everyday',
        recognition_tags={'wearing_profile': {
            'layering_region': 'upper_body', 'can_wear_alone': False,
            'can_layer_over': True, 'can_layer_under': False,
            'requires_inner_layer': True, 'wearing_modes': ['outer_layer_closed'],
        }},
    ))
    class Embed:
        def create_embedding(self, text):
            assert 'can_wear_alone=True' in text
            assert 'requires_inner_layer=False' in text
            return [.25]

    saved = ItemService(repository, Embed()).update_item('u', cardigan.id, ClothingItemUpdateRequest(
        category='Tops', subtype='Sweater', color='Green', season='Fall',
        style='Casual', occasion='Everyday',
    ))

    assert saved.wearing_profile['can_wear_alone'] is True
    assert saved.wearing_profile['requires_inner_layer'] is False
    assert saved.wearing_profile['can_layer_over'] is None
    assert saved.wearing_profile['can_layer_under'] is None
    assert saved.wearing_profile['wearing_modes'] == ['standalone']


def test_user_layering_override_wins_and_is_versioned(repository):
    item = repository.add_item(ClothingItemRecord(
        user_id='u', image_url='https://example.test/sweater.jpg',
        category='Tops', subtype='Sweater', color='Gray', season='Winter',
        style='Casual', occasion='Everyday', recognition_tags={'wearing_profile': PROFILE},
    ))
    before_revision = revision(item)
    class Embed:
        def create_embedding(self, text):
            assert 'can_layer_over=False' in text
            return [.75]

    saved = ItemService(repository, Embed()).update_item('u', item.id, ClothingItemUpdateRequest(
        category='Tops', subtype='Sweater', color='Gray', season='Winter',
        style='Casual', occasion='Everyday', wearing_profile_override=True,
        wearing_profile={
            'can_wear_alone': True,
            'can_layer_over': False,
            'can_layer_under': True,
            'requires_inner_layer': False,
        },
    ))

    assert saved.wearing_profile['can_layer_over'] is False
    assert saved.wearing_profile['wearing_modes'] == ['standalone', 'inner_layer']
    assert saved.wearing_profile['evidence'] == 'User-confirmed layering capabilities.'
    assert revision(saved) != before_revision


def test_partial_layering_override_keeps_new_taxonomy_defaults(repository):
    cardigan = repository.add_item(ClothingItemRecord(
        user_id='u', image_url='https://example.test/cardigan-2.jpg',
        category='Outerwear', subtype='Cardigan', color='Gray', season='Winter',
        style='Casual', occasion='Everyday', recognition_tags={'wearing_profile': PROFILE},
    ))
    class Embed:
        def create_embedding(self, _): return [.1]

    saved = ItemService(repository, Embed()).update_item('u', cardigan.id, ClothingItemUpdateRequest(
        category='Tops', subtype='Sweater', color='Gray', season='Winter',
        style='Casual', occasion='Everyday', wearing_profile_override=True,
        wearing_profile={'can_layer_over': False},
    ))

    assert saved.wearing_profile['can_wear_alone'] is True
    assert saved.wearing_profile['requires_inner_layer'] is False
    assert saved.wearing_profile['can_layer_over'] is False

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
    assert records[-1]['normalized_payload']['wearing_profile']==PROFILE_WITH_CAPACITY


def test_unknown_capacity_fields_do_not_invalidate_legacy_outfit_revisions():
    from app.outfits.service import revision

    base = dict(
        user_id='u', image_url='https://example.test/i.jpg', category='Tops',
        recognition_tags={'wearing_profile': PROFILE},
    )
    legacy = ClothingItemRecord(**base)
    explicit_unknown = ClothingItemRecord(**{
        **base,
        'recognition_tags': {'wearing_profile': PROFILE_WITH_CAPACITY},
    })
    recognized_capacity = ClothingItemRecord(**{
        **base,
        'recognition_tags': {'wearing_profile': PROFILE | {'layering_bulk': 'high'}},
    })

    assert legacy.wearing_profile == PROFILE
    assert explicit_unknown.wearing_profile == PROFILE
    assert revision(explicit_unknown) == revision(legacy)
    assert revision(recognized_capacity) != revision(legacy)
