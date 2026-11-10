from dataclasses import replace
import pytest
from app.models.domain import ClothingItemRecord, RecognitionJobRecord, ClothingAnalysis
from app.services.recognition_pipeline import RecognitionPipeline
from app.services.recognition_service import ClothingRecognitionService
from app.services.item_service import ItemService
from app.services.recognition_output import RecognitionSchemaError
from app.models.api import ClothingItemUpdateRequest

class Storage:
    def signed_image_url(self,*a,**kw):return 'https://example.test/photo'
class NeverEmbed:
    def create_embedding(self,*a):raise AssertionError('Failed recognition must not embed')
class Fallback:
    def analyze(self,*a,**kw):return ClothingAnalysis(category='Uncategorized',source='Heuristic Fallback')

def test_unavailable_vision_never_returns_filename_guess(monkeypatch):
    from app.services import recognition_service as module
    monkeypatch.setattr(module,'settings',replace(
        module.settings, openai_api_key=None, ai_api_key=None,
        recognition_ai_api_key=None,
    ))
    with pytest.raises(RuntimeError):
        ClothingRecognitionService().analyze('blue_yoga_pants.jpg','https://example.test/photo')

def test_fallback_is_retryable_then_terminal_without_success(repository):
    from app.core.config import settings
    item=repository.add_item(ClothingItemRecord(user_id='u',category='Uncategorized',image_url='https://example.test/photo',image_path='photo',recognition_status='queued'))
    job=repository.create_recognition_job(RecognitionJobRecord(user_id='u',clothing_item_id=item.id,filename='photo',image_path='photo',image_url=item.image_url))
    pipeline=RecognitionPipeline(repository,Fallback(),NeverEmbed(),Storage())
    pipeline.process_job(job.model_copy(update={'attempts':1}))
    current=repository.get_item(item.id,'u')
    assert current.recognition_status=='queued'
    assert current.recognition_source=='Analyzing'
    assert current.category=='Uncategorized'
    pipeline.process_job(job.model_copy(update={'attempts':settings.recognition_worker_max_attempts}))
    current=repository.get_item(item.id,'u')
    assert current.recognition_status=='failed'
    assert current.metadata['recognition_error']['phase']=='recognition'

@pytest.mark.parametrize('status,source',[('queued','Analyzing'),('processing','Analyzing'),('failed','Recognition Failed'),('complete','Heuristic Fallback')])
def test_opening_placeholder_does_not_confirm(repository,status,source):
    item=repository.add_item(ClothingItemRecord(user_id='u',category='Uncategorized',image_url='https://example.test/photo',recognition_status=status,recognition_source=source))
    payload=ClothingItemUpdateRequest(category='Uncategorized',color='Unknown',season='Summer',style='Casual',occasion='Everyday',edit_source='ios_card_open')
    saved=ItemService(repository,NeverEmbed()).update_item('u',item.id,payload)
    assert saved.recognition_status==status
    assert not (saved.metadata or {}).get('label_confirmation')

def test_model_exception_propagates_instead_of_fallback(monkeypatch):
    service=ClothingRecognitionService()
    monkeypatch.setattr(service,'_openai_vision_status',lambda url:(True,''))
    def fail(**kw):raise TimeoutError('private URL')
    monkeypatch.setattr(service,'_analyze_with_openai_vision',fail)
    with pytest.raises(TimeoutError):service.analyze('blue_shirt.jpg','https://example.test/photo')


def test_exhausted_structured_output_is_terminal_without_durable_retry(repository):
    class InvalidOutput:
        def analyze(self, *args, **kwargs):
            raise RecognitionSchemaError("missing required field")

    item = repository.add_item(ClothingItemRecord(
        user_id='u', category='Uncategorized', image_url='https://example.test/photo',
        image_path='photo', recognition_status='queued',
    ))
    repository.create_recognition_job(RecognitionJobRecord(
        user_id='u', clothing_item_id=item.id, filename='photo', image_path='photo', image_url=item.image_url,
    ))
    claimed = repository.claim_recognition_jobs(batch_size=1, max_attempts=3)[0]
    RecognitionPipeline(repository, InvalidOutput(), NeverEmbed(), Storage()).process_job(claimed)
    current = repository.get_item(item.id, 'u')
    assert current.recognition_status == 'failed'
    assert current.recognition_source == 'Recognition Failed'
    assert repository.queue_health('u')['status_counts']['dead_letter'] == 1
