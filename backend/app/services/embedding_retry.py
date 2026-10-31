"""Durable embedding repair using item metadata and conditional writes."""
import hashlib
import math
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from app.core.config import settings
from app.services.embedding_service import EmbeddingService,item_embedding_text

FIELDS=('category','subtype','color','season','style','occasion','recognition_summary','image_path','recognition_status')
STATE='semantic_embedding'


def now():return datetime.now(timezone.utc)


def input_hash(item):
    return hashlib.sha256(f'{settings.openai_embedding_model}|{settings.openai_embedding_dimensions}|{item_embedding_text(item)}'.encode()).hexdigest()


def valid(vector):return bool(vector) and all(math.isfinite(x) for x in vector) and any(x!=0 for x in vector)


def state_after_attempt(item,vector,attempts=1):
    return {'status':'complete' if valid(vector) else 'pending','input_hash':input_hash(item),
        'attempts':attempts,'model':settings.openai_embedding_model,'dimensions':settings.openai_embedding_dimensions,
        'retry_at':None if valid(vector) else (now()+timedelta(seconds=min(3600,60*2**min(attempts-1,6)))).isoformat(),
        'last_error':None if valid(vector) else 'Embedding request failed; background retry scheduled'}


def annotate_attempt(item,metadata,vector):
    return {**metadata,STATE:state_after_attempt(item,vector)}


def same_snapshot(a,b):
    return (a.user_id==b.user_id and a.semantic_vector is None and b.semantic_vector is None and
            (a.metadata or {})==(b.metadata or {}) and all(getattr(a,k)==getattr(b,k) for k in FIELDS))


class EmbeddingRetry:
    def __init__(self,repository,service=None):
        self.repository=repository;self.service=service or EmbeddingService()

    def run_once(self,limit=3):
        attempted=0;completed=0
        for item in self.repository.list_embedding_retry_candidates():
            if attempted>=limit:break
            if item.recognition_status not in {'manual','complete'} or item.semantic_vector is not None:continue
            state=(item.metadata or {}).get(STATE,{})
            unchanged=state.get('input_hash')==input_hash(item)
            due=state.get('lease_until') if state.get('status')=='processing' else state.get('retry_at')
            if unchanged and due:
                try:
                    if datetime.fromisoformat(due)>now():continue
                except (ValueError,TypeError):pass
            attempt=state.get('attempts',0)+1 if unchanged else 1
            claim={**state,'status':'processing','input_hash':input_hash(item),'attempts':attempt,
                   'lease_token':str(uuid4()),'lease_until':(now()+timedelta(seconds=120)).isoformat()}
            claimed=self.repository.update_embedding_if_current(item,{'metadata':{**(item.metadata or {}),STATE:claim}})
            if claimed is None:continue
            attempted+=1
            try:vector=self.service.create_embedding(item_embedding_text(claimed))
            except Exception:vector=None
            if not valid(vector):vector=None
            metadata={**(claimed.metadata or {}),STATE:state_after_attempt(claimed,vector,attempt)}
            updated=self.repository.update_embedding_if_current(claimed,{'semantic_vector':vector,'metadata':metadata})
            if updated is not None and vector is not None:completed+=1
        return {'attempted':attempted,'completed':completed}
