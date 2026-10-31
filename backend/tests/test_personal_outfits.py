from uuid import uuid4
from datetime import datetime,timezone,timedelta
import pytest
from fastapi import HTTPException
from test_outfit_library import setup,Signer
from app.outfits.personal import PersonalOutfits,PersonalOutfitRequest,WearRequest,OutfitFeedbackRequest
from app.outfits.recommendations import WearPolicy,wear_effect,recommend_library
from app.services.recommendation import RecommendationEngine
from app.models.domain import ClothingItemRecord, RecommendationContext


def test_feedback_state_rows_use_the_tables_real_sort_column():
    class Result:
        data=[]
    class Query:
        def __init__(self):self.ordered_by=None
        def select(self,*args):return self
        def eq(self,*args):return self
        def order(self,column):self.ordered_by=column;return self
        def range(self,*args):return self
        def execute(self):
            assert self.ordered_by=='composition_signature'
            return Result()
    class Client:
        def table(self,*args):return Query()
    class Store:
        client=Client()
    assert PersonalOutfits(object(),Store()).rows('user_outfit_feedback_state','user-1')==[]


def test_save_is_idempotent_scoped_and_visible_per_item(setup):
    uid,top,bottom,lib,_=setup;p=PersonalOutfits(lib.repository,lib.store)
    out=p.save(uid,PersonalOutfitRequest(item_ids=[top.id,bottom.id]))
    assert out.id==p.save(uid,PersonalOutfitRequest(item_ids=[bottom.id,top.id])).id
    assert len(p.list(uid))==1
    assert lib.list(uid,Signer(),'',top.id).total==1
    assert lib.list(uid,Signer(),'',bottom.id).total==1
    assert lib.list(str(uuid4()),Signer(),'').total==0
    with pytest.raises(HTTPException):p.save(str(uuid4()),PersonalOutfitRequest(item_ids=[top.id]))
    with pytest.raises(HTTPException):p.save(uid,PersonalOutfitRequest(item_ids=[top.id,top.id]))
    lib.repository.update_item(top.id,{'color':'Blue'},uid)
    assert lib.list(uid,Signer(),'').outfits[0].items[0].id
    lib.repository.delete_item(bottom.id,uid)
    assert lib.list(uid,Signer(),'').total==0


def test_wear_idempotency_undo_ownership(setup):
    uid,top,bottom,lib,_=setup;p=PersonalOutfits(lib.repository,lib.store)
    event=WearRequest(id=uuid4(),item_ids=[top.id,bottom.id],worn_at=datetime.now(timezone.utc))
    p.record_wear(uid,event);p.record_wear(uid,event)
    assert len(p.rows('outfit_wear_events',uid))==1
    with pytest.raises(HTTPException):p.record_wear(uid,event.model_copy(update={'item_ids':[top.id]}))
    p.undo_wear(str(uuid4()),str(event.id))
    assert len(p.rows('outfit_wear_events',uid))==1
    p.undo_wear(uid,str(event.id));assert p.rows('outfit_wear_events',uid)==[]


def test_today_selection_persists_replaces_and_reports_latest_time(setup):
    uid,top,bottom,lib,_=setup;p=PersonalOutfits(lib.repository,lib.store)
    today=datetime.now(timezone.utc).date()
    first=WearRequest(id=uuid4(),item_ids=[top.id],worn_at=datetime.now(timezone.utc),wear_date=today)
    saved=p.record_wear(uid,first)
    status=p.wear_status(uid,[top.id],today)
    assert status.selected_today.id==first.id
    assert [item.id for item in status.selected_today_items]==[top.id]
    assert status.latest_worn_at==datetime.fromisoformat(saved['worn_at'])

    second=WearRequest(id=uuid4(),item_ids=[bottom.id],worn_at=datetime.now(timezone.utc),wear_date=today)
    p.record_wear(uid,second)
    assert [event['id'] for event in p.rows('outfit_wear_events',uid)]==[str(second.id)]
    assert p.wear_status(uid,[top.id],today).latest_worn_at is None
    assert p.wear_status(uid,[bottom.id],today).selected_today.id==second.id

    p.undo_wear(uid,str(second.id))
    assert p.wear_status(uid,[],today).selected_today is None


@pytest.mark.parametrize('days,blocked,penalty',[(0,True,40),(1.999,True,40),(2,False,40),(5,False,20),(8,False,10),(14,False,0),(30,False,0)])
def test_decay_boundaries(setup,days,blocked,penalty):
    _,top,_,_,_=setup;now=datetime.now(timezone.utc)
    events=[{'item_ids':[top.id],'worn_at':(now-timedelta(days=days)).isoformat()}]
    b,p=wear_effect([top],events,WearPolicy(),now)
    assert b==blocked and p==pytest.approx(penalty)


def test_recent_overlap_excludes_other_outfit_without_fallback(setup,monkeypatch):
    uid,top,bottom,lib,_=setup;p=PersonalOutfits(lib.repository,lib.store)
    shoe=lib.repository.add_item(ClothingItemRecord(
        id=str(uuid4()),user_id=uid,image_url='shoe.jpg',image_path='shoe.jpg',
        category='Shoes',subtype='Sneakers',recognition_status='complete'))
    p.save(uid,PersonalOutfitRequest(item_ids=[top.id,bottom.id,shoe.id]))
    monkeypatch.setattr('app.outfits.recommendations.build_store',lambda _:lib.store)
    class NoEmbedding:
        def create_embedding(self,*args):return None
    engine=RecommendationEngine(embedding_service=NoEmbedding());context=RecommendationContext(occasion='Everyday',temperature_f=72,limit=5)
    result=recommend_library(lib.repository,engine,uid,context,{})
    assert len(result)==1 and result[0].original_score==result[0].score
    e=WearRequest(id=uuid4(),item_ids=[top.id],worn_at=datetime.now(timezone.utc))
    p.record_wear(uid,e)
    assert recommend_library(lib.repository,engine,uid,context,{})==[]
    p.undo_wear(uid,str(e.id))
    p.record_wear(uid,e.model_copy(update={'worn_at':datetime.now(timezone.utc)-timedelta(days=5)}))
    result=recommend_library(lib.repository,engine,uid,context,{})
    assert result[0].wear_penalty==20
    assert result[0].score==round(max(0,result[0].original_score+result[0].personalization_score-20),2)


def test_user_saved_composition_is_recommended_without_system_override(setup, monkeypatch):
    uid,top,_,lib,_=setup
    lib.repository.update_item(
        top.id,
        {'category':'Intimates','subtype':'Tights'},
        uid,
    )
    PersonalOutfits(lib.repository,lib.store).save(
        uid,PersonalOutfitRequest(item_ids=[top.id])
    )
    monkeypatch.setattr('app.outfits.recommendations.build_store',lambda _:lib.store)
    class NoEmbedding:
        def create_embedding(self,*args):return None
    engine=RecommendationEngine(embedding_service=NoEmbedding())
    context=RecommendationContext(occasion='Everyday',temperature_f=72,limit=5)
    result=recommend_library(lib.repository,engine,uid,context,{})
    assert len(result)==1
    assert [item.id for item in result[0].items]==[top.id]


def test_latest_wear_and_future_validation(setup):
    uid,top,_,lib,_=setup;p=PersonalOutfits(lib.repository,lib.store);now=datetime.now(timezone.utc)
    with pytest.raises(HTTPException):p.record_wear(uid,WearRequest(id=uuid4(),item_ids=[top.id],worn_at=now+timedelta(days=1)))
    events=[{'item_ids':[top.id],'worn_at':(now-timedelta(days=d)).isoformat()} for d in [8,1]]
    assert wear_effect([top],events,WearPolicy(),now)[0]


def test_feedback_is_owned_idempotent_and_tracks_current_state(setup):
    uid,top,bottom,lib,_=setup;p=PersonalOutfits(lib.repository,lib.store)
    event=OutfitFeedbackRequest(id=uuid4(),outfit_id=uuid4(),item_ids=[top.id,bottom.id],
        action='disliked',reason_codes=['color_pattern'],surface='library')
    first=p.record_feedback(uid,event);second=p.record_feedback(uid,event)
    assert first==second
    assert len(p.rows('outfit_feedback_events',uid))==1
    state=p.rows('user_outfit_feedback_state',uid)
    assert len(state)==1 and state[0]['state']=='disliked'
    assert p.composition_signature([top.id,bottom.id]) in p.disliked_signatures(uid)
    with pytest.raises(HTTPException):
        p.record_feedback(str(uuid4()),event)

    liked=event.model_copy(update={'id':uuid4(),'action':'liked','reason_codes':[]})
    p.record_feedback(uid,liked)
    signature=p.composition_signature([top.id,bottom.id])
    assert signature in p.liked_signatures(uid)
    assert signature not in p.disliked_signatures(uid)
