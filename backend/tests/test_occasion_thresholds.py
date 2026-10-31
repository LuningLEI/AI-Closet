import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.api import ClothingItemUpdateRequest, UserPreferencesUpdateRequest
from app.models.domain import ClothingItemRecord, ClothingAnalysis, RecognitionJobRecord
from app.services.occasion_support import effective_occasion, occasion_for_display
from app.services.occasion_thresholds import user_thresholds, update_user_thresholds, validate_thresholds
from app.services.response_signing import ResponseSigningService
from app.services.item_service import ItemService
from app.services.recommendation.rules import item_occasion_tokens
from app.services.recognition_pipeline import RecognitionPipeline
from tools.evaluation.occasion_thresholds import reapply_user_occasions


class Storage:
    def signed_image_url(self, path, **kwargs): return 'https://example.test/a.jpg'
    def signed_image_urls(self, paths): return dict.fromkeys(paths, 'https://example.test/a.jpg')
    def fallback_image_url(self, path): return None


class Embeddings:
    def create_embedding(self, text): return None


def item(repository, owner='a', item_id=None, occasion=''):
    return repository.add_item(ClothingItemRecord(
        id=item_id or owner,user_id=owner,image_url='https://example.test/a.jpg', category='Tops', occasion=occasion,
        recognition_tags={'occasion_scores':[{'occasion':'Everyday','score':0.75},{'occasion':'Work','score':0.7}]},
    ))


def test_per_user_policy_persists_and_display_and_recommendation_are_isolated(repository):
    a,b=item(repository,'a'),item(repository,'b')
    assert set(user_thresholds(repository,'a').values())=={0.8}
    thresholds=update_user_thresholds(repository,'a',{'Everyday':0.85,'Work':0.65})
    assert thresholds['Date']==0.8
    assert user_thresholds(repository,'b')['Work']==0.8
    repository.upsert_preferences('a',{'nickname':'New nickname'})
    repository.upsert_preferences('a',{'preferences':{'profile':{'daily_occasions':['Travel']}}})
    assert user_thresholds(repository,'a')['Work']==0.65
    signed=ResponseSigningService(Storage(),repository).items([a,b],'http://localhost')
    assert [i.occasion for i in signed]==['Work','Everyday']
    assert item_occasion_tokens(signed[0])=={'work'}
    assert item_occasion_tokens(signed[1])=={'everyday'}
    assert repository.get_item('a').occasion==''


@pytest.mark.parametrize('values',[{'Bad':0.5},{'Work':-0.1},{'Work':1.1},{'Work':True},{'Work':float('nan')},{'Work':'0.8'}])
def test_invalid_thresholds_rejected(values):
    with pytest.raises(ValueError): validate_thresholds(values)
    with pytest.raises(ValidationError): UserPreferencesUpdateRequest(preferences={'occasion_thresholds':values})


def test_backfill_uses_saved_scores_preserves_other_user_and_raw_data(repository,tmp_path):
    a,b=item(repository,'a'),item(repository,'b')
    initial=a.model_dump()
    preview=reapply_user_occasions(repository,'a',dry_run=True,backup_dir=tmp_path/'backups')
    assert preview['changes'][0]['after']=='Everyday'
    assert repository.get_item('a').model_dump()==initial
    assert not (tmp_path/'backups').exists()
    result=reapply_user_occasions(repository,'a',backup_dir=tmp_path/'backups')
    after=repository.get_item('a').model_dump()
    assert after=={**initial,'occasion':'Everyday'}
    assert repository.get_item('b')==b
    assert Path(result['backup']).exists()
    assert reapply_user_occasions(repository,'a')['changes']==[]


def test_edit_snapshot_survives_personal_threshold_change(repository):
    a=item(repository,'a',occasion='Everyday')
    before=user_thresholds(repository,'a')
    update_user_thresholds(repository,'a',{'Work':0.65})
    updated=ItemService(repository,Embeddings()).update_item('a',a.id,ClothingItemUpdateRequest(
        category='Tops',color='Blue',season='All-Season',style='Casual',occasion='Everyday',
        occasion_before='Everyday',occasion_thresholds_at_edit=before,
    ))
    assert effective_occasion(updated,user_thresholds(repository,'a'))=='Work'
    assert updated.metadata['occasion_overrides']=={'added':[],'removed':[]}
    events=json.loads(repository.item_edit_events_path.read_text())
    assert events[0]['changed_fields']==['color']


def test_worker_persists_personal_threshold_snapshot(repository):
    a=item(repository,'a')
    policy=update_user_thresholds(repository,'a',{'Work':0.65})
    class Recognizer:
        def analyze(self,*args,**kwargs):
            return ClothingAnalysis(source='OpenAI Vision',occasion_scores=a.recognition_tags['occasion_scores'])
    job=repository.create_recognition_job(RecognitionJobRecord(user_id='a',clothing_item_id='a',filename='a.jpg',image_url=a.image_url))
    RecognitionPipeline(repository,Recognizer(),Embeddings(),Storage()).process_job(job)
    saved=repository.get_item('a')
    assert saved.occasion=='Work'
    assert saved.recognition_tags['occasion_thresholds']==policy
    assert saved.recognition_tags['occasion_scores']==a.recognition_tags['occasion_scores']
