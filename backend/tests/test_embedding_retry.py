from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from app.models.domain import ClothingItemRecord
from app.services.embedding_retry import EmbeddingRetry,STATE,state_after_attempt,now


class Embed:
    def __init__(self,vector=None):self.vector=vector;self.calls=0
    def create_embedding(self,text):self.calls+=1;return self.vector


def garment(repository):
    item=ClothingItemRecord(user_id='u',category='Tops',subtype='Blouse',image_url='',recognition_status='manual',metadata={'manual_override':True})
    repository.add_item(item);return item


def test_retry_persists_and_survives_new_worker(repository):
    item=garment(repository);fail=Embed();EmbeddingRetry(repository,fail).run_once()
    saved=repository.get_item(item.id,'u');assert saved.semantic_vector is None and saved.metadata[STATE]['status']=='pending'
    assert saved.metadata[STATE]['attempts']==1 and saved.metadata['manual_override']
    success=Embed([1.,2.]);EmbeddingRetry(repository,success).run_once();assert success.calls==0
    saved.metadata[STATE]['retry_at']=(now()-timedelta(seconds=1)).isoformat()
    repository.update_item(item.id,{'metadata':saved.metadata},'u')
    assert EmbeddingRetry(repository,success).run_once()['completed']==1
    fixed=repository.get_item(item.id,'u');assert fixed.semantic_vector==[1.,2.] and fixed.metadata[STATE]['attempts']==2


def test_edit_during_request_does_not_receive_old_vector(repository):
    item=garment(repository)
    class Edit:
        def create_embedding(self,text):
            repository.update_item(item.id,{'color':'Blue','metadata':{'manual_override':True}},'u')
            return [1.,2.]
    assert EmbeddingRetry(repository,Edit()).run_once()['completed']==0
    saved=repository.get_item(item.id,'u');assert saved.color=='Blue' and saved.semantic_vector is None
    assert saved.metadata=={'manual_override':True}
    assert EmbeddingRetry(repository,Embed([3.,4.])).run_once()['completed']==1


def test_atomic_claim_avoids_concurrent_embedding_calls(repository):
    garment(repository)
    import threading
    entered=threading.Event();release=threading.Event()
    class Slow(Embed):
        def create_embedding(self,text):
            self.calls+=1;entered.set();release.wait(3);return [1.,2.]
    service=Slow()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(EmbeddingRetry(repository,service).run_once)
        assert entered.wait(3)
        second=pool.submit(EmbeddingRetry(repository,service).run_once)
        assert second.result()['attempted']==0
        release.set();assert first.result()['completed']==1
    assert service.calls==1


def test_expired_lease_and_missing_metadata_are_repaired(repository):
    item=garment(repository)
    state=state_after_attempt(item,None);state.update(status='processing',lease_until=(now()-timedelta(seconds=1)).isoformat())
    repository.update_item(item.id,{'metadata':{STATE:state}},'u')
    assert EmbeddingRetry(repository,Embed([1.,2.])).run_once()['completed']==1


def test_deleted_item_not_resurrected(repository):
    item=garment(repository)
    class Delete:
        def create_embedding(self,text):repository.delete_item(item.id,'u');return [1.,2.]
    assert EmbeddingRetry(repository,Delete()).run_once()['completed']==0
    assert repository.get_item(item.id,'u') is None
