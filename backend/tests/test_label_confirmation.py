import json
from app.models.api import ClothingItemUpdateRequest
from app.models.domain import ClothingItemRecord, ClothingAnalysis, RecognitionJobRecord
from app.services.item_service import ItemService
from app.services.recognition_pipeline import RecognitionPipeline
from app.services.occasion_support import effective_occasion

class Embedding:
    def create_embedding(self,text):return [.25]
class Storage:
    def signed_image_url(self,*a,**kw):return 'https://example.test/photo.jpg'
class Recognizer:
    def analyze(self,*a,**kw):return ClothingAnalysis(category='Tops',color='Red',seasons=['Summer'],style='Casual',occasion='Everyday',source='OpenAI Vision')

def payload(**kw):
    return ClothingItemUpdateRequest(category='Bottoms',subtype='Shorts',color='Blue',season='Summer',style='Casual',occasion='Travel',edit_source='ios_card_open',**kw)

def setup(repository):
    item=repository.add_item(ClothingItemRecord(user_id='u',image_path='photo.jpg',image_url='https://example.test/photo.jpg',category='Bottoms',subtype='Shorts',color='Blue',season='Summer',style='Casual',occasion='Travel',semantic_vector=[.5]))
    job=repository.create_recognition_job(RecognitionJobRecord(user_id='u',clothing_item_id=item.id,image_path=item.image_path,image_url=item.image_url,filename='photo.jpg'))
    return item,job

def test_confirm_does_not_call_model_and_freezes_displayed_occasion(repository):
    item,job=setup(repository)
    class Never:
        def create_embedding(self,*a):raise AssertionError('Opening card must not call embedding')
    confirmed=ItemService(repository,Never()).update_item('u',item.id,payload())
    assert confirmed.semantic_vector==[.5]
    assert effective_occasion(confirmed,.01)=='Travel'
    RecognitionPipeline(repository,Recognizer(),Never(),Storage()).process_job(job)
    saved=repository.get_item(item.id,'u')
    assert saved.color=='Blue' and saved.occasion=='Travel'
    records=json.loads(repository.recognition_records_path.read_text())
    assert records[-1]['color']=='Red'  # Machine result remains separately auditable.

def test_confirmation_during_embedding_wins(repository):
    item,job=setup(repository)
    class Concurrent:
        def create_embedding(self,text):
            ItemService(repository,Embedding()).update_item('u',item.id,payload())
            return [.9]
    RecognitionPipeline(repository,Recognizer(),Concurrent(),Storage()).process_job(job)
    saved=repository.get_item(item.id,'u')
    assert saved.color=='Blue' and saved.category=='Bottoms'
    assert saved.semantic_vector==[.5]
    assert saved.metadata['label_confirmation']['labels']['color']=='Blue'

def test_confirm_persists_what_was_shown_even_if_prediction_changed(repository):
    item,_=setup(repository)
    repository.update_item(item.id,{'color':'Red'},'u')
    saved=ItemService(repository,Embedding()).update_item('u',item.id,payload())
    assert saved.color=='Blue'
    assert saved.semantic_vector is None  # Background retry uses the restored labels.

def test_manual_edit_during_embedding_keeps_new_labels_and_vector(repository):
    item,job=setup(repository)
    class Concurrent:
        def create_embedding(self,text):
            edit=payload().model_copy(update={'edit_source':'ios','color':'Green'})
            ItemService(repository,Embedding()).update_item('u',item.id,edit)
            return [.9]
    RecognitionPipeline(repository,Recognizer(),Concurrent(),Storage()).process_job(job)
    saved=repository.get_item(item.id,'u')
    assert saved.color=='Green'
    assert saved.semantic_vector==[.25]
    assert saved.metadata['label_confirmation']['labels']['color']=='Green'
