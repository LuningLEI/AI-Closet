import asyncio
import json
from io import BytesIO
from fastapi import UploadFile
from app.models.domain import ClothingItemRecord,ClothingAnalysis
from app.models.api import ImageEditMetadata
from app.services.item_service import ItemService
from app.services.recognition_pipeline import RecognitionPipeline

class Storage:
    async def store_image(self,file,user_id):return {'image_path':'new.jpg','image_url':'https://example.test/new.jpg'}
    def signed_image_url(self,*args,**kwargs):return 'https://example.test/signed.jpg'
    def delete_image(self,*args):pass
class Embeddings:
    def create_embedding(self,text):return [0.1]


def test_crop_keeps_manual_card_and_new_model_record(repository):
    original=repository.add_item(ClothingItemRecord(id='manual',user_id='u',image_path='old.jpg',image_url='https://example.test/old.jpg',category='Activewear',subtype='Athletic Jacket',color='Black, Olive',season='Spring',style='Sporty',occasion='Work',recognition_summary='My jacket',recognition_status='manual',recognition_source='Manual Edit',metadata={'manual_override':True},recognition_tags={'category':'Activewear'}))
    edited=asyncio.run(ItemService(repository,Embeddings(),Storage()).replace_item_image('u',original.id,UploadFile(file=BytesIO(b'jpeg'),filename='crop.jpg'),'http://test/',ImageEditMetadata(rotation_quarter_turns=1,zoom_scale=1,drag_x=0,drag_y=0,editor_side=300)))
    assert edited.recognition_summary=='My jacket'
    assert edited.recognition_tags==original.recognition_tags
    assert repository.claim_recognition_jobs(1,3) == []
    assert edited.image_path == 'new.jpg'
    assert edited.semantic_vector == original.semantic_vector
    assert edited.feature_vector == original.feature_vector
    assert edited.metadata['label_confirmation']['labels']['color'] == original.color
    assert edited.metadata['last_image_edit']['rotation_quarter_turns'] == 1


def test_failed_recognition_retains_manual_protection_for_retry(repository):
    from app.models.domain import RecognitionJobRecord
    item=repository.add_item(ClothingItemRecord(id='retry',user_id='u',category='Tops',image_path='new.jpg',image_url='https://example.test/new.jpg',color='Olive',recognition_summary='My note',metadata={'manual_override':True,'occasion_overrides':{'added':['Work'],'removed':['Everyday']}}))
    job=repository.create_recognition_job(RecognitionJobRecord(user_id='u',clothing_item_id=item.id,image_path=item.image_path,image_url=item.image_url,filename='crop.jpg'))
    class Failure:
        def analyze(self,*args,**kwargs):raise RuntimeError('temporary failure')
    RecognitionPipeline(repository,Failure(),Embeddings(),Storage()).process_job(job)
    saved=repository.get_item(item.id,'u')
    assert saved.color=='Olive' and saved.recognition_summary=='My note'
    assert saved.metadata['manual_override'] is True
    assert saved.metadata['occasion_overrides']==item.metadata['occasion_overrides']


def test_photo_commit_response_lost_is_reconciled_without_replay(repository, monkeypatch):
    import httpx
    item=repository.add_item(ClothingItemRecord(id='lost', user_id='u', image_path='old.jpg', image_url='old.jpg', category='Tops'))
    commit=repository.commit_item_change
    calls=[]
    def lost_response(*args, **kwargs):
        calls.append(1)
        commit(*args, **kwargs)
        raise httpx.ReadError('TLS connection interrupted')
    monkeypatch.setattr(repository,'commit_item_change',lost_response)
    result=asyncio.run(ItemService(repository,Embeddings(),Storage()).replace_item_image('u',item.id,UploadFile(file=BytesIO(b'jpeg'),filename='crop.jpg'),'http://test/'))
    assert result.image_path=='new.jpg'
    assert len(calls)==1
    assert len(json.loads(repository.item_edit_events_path.read_text()))==1


def test_photo_commit_not_saved_keeps_original_and_returns_safe_error(repository, monkeypatch):
    import httpx
    import pytest
    from fastapi import HTTPException
    item=repository.add_item(ClothingItemRecord(id='lost', user_id='u', image_path='old.jpg', image_url='old.jpg', category='Tops'))
    calls=[]
    def fail(*args, **kwargs):
        calls.append(1)
        raise httpx.ReadError('SSL private connection details')
    monkeypatch.setattr(repository,'commit_item_change',fail)
    with pytest.raises(HTTPException) as error:
        asyncio.run(ItemService(repository,Embeddings(),Storage()).replace_item_image('u',item.id,UploadFile(file=BytesIO(b'jpeg'),filename='crop.jpg'),'http://test/'))
    assert error.value.status_code==503
    assert 'SSL' not in error.value.detail
    assert len(calls)==1
    assert repository.get_item(item.id,'u').image_path=='old.jpg'
