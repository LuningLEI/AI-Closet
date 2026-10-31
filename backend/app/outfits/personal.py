"""User-owned compositions and idempotent wear events; no paid model calls."""
import json
import hashlib
from datetime import date, datetime, timezone, timedelta
from uuid import UUID, uuid5, NAMESPACE_URL
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from fastapi import HTTPException
from app.outfits.models import OutfitDTO
from app.models.domain import ClothingItemRecord
from app.services.taste_profile import snapshot_items
from app.services.taste_profile_service import TasteProfileService

class PersonalOutfitRequest(BaseModel):
    item_ids: list[UUID] = Field(min_length=1,max_length=12)
    title: str = Field(default='My outfit',min_length=1,max_length=120)

class WearRequest(BaseModel):
    id: UUID
    item_ids: list[UUID] = Field(min_length=1,max_length=12)
    worn_at: datetime
    wear_date: date | None = None

class WearEvent(WearRequest):
    user_id: str
    created_at: datetime | None = None

class WearStatus(BaseModel):
    selected_today: WearEvent | None = None
    selected_today_items: list[ClothingItemRecord] = Field(default_factory=list)
    latest_worn_at: datetime | None = None
    liked: bool = False

class OutfitFeedbackRequest(BaseModel):
    id: UUID
    outfit_id: UUID | None = None
    item_ids: list[UUID] = Field(min_length=1,max_length=12)
    action: Literal['liked','disliked']
    reason_codes: list[str] = Field(default_factory=list,max_length=4)
    note: str | None = Field(default=None,max_length=500)
    surface: Literal['today','library','recommendations','chat']
    context: dict = Field(default_factory=dict)
    target_item_ids: list[UUID] = Field(default_factory=list,max_length=12)

    @model_validator(mode='after')
    def validate_reasons(self):
        allowed={'color_pattern','style','too_formal','too_casual','weather_mismatch',
                 'occasion_mismatch','pieces_do_not_match','layering','shoes_accessories',
                 'dislike_item','too_repetitive','other'}
        if len(set(self.reason_codes))!=len(self.reason_codes) or not set(self.reason_codes)<=allowed:
            raise ValueError('Invalid feedback reason.')
        return self

class OutfitFeedbackEvent(OutfitFeedbackRequest):
    user_id: str
    composition_signature: str
    created_at: datetime | None = None


class PersonalOutfits:
    def __init__(self, repository, store):
        self.repository,self.store=repository,store
        if not hasattr(store,'client'):
            with store.db() as db:
                db.execute('create table if not exists personal_outfits (id text primary key,user_id text not null,data text not null)')
                db.execute('create table if not exists outfit_wear_events (id text primary key,user_id text not null,data text not null)')
                db.execute('create table if not exists outfit_daily_selections (key text primary key,user_id text not null,event_id text not null,wear_date text not null)')
                db.execute('create table if not exists outfit_feedback_events (id text primary key,user_id text not null,data text not null)')
                db.execute('create table if not exists user_outfit_feedback_state (key text primary key,user_id text not null,data text not null)')
                db.execute('create table if not exists user_taste_profiles (user_id text primary key,data text not null)')

    def rows(self,table,uid):
        if hasattr(self.store,'client'):
            out=[]
            while True:
                order_column = 'composition_signature' if table == 'user_outfit_feedback_state' else 'id'
                batch=(self.store.client.table(table).select('*').eq('user_id',uid)
                       .order(order_column).range(len(out),len(out)+499).execute().data or [])
                out.extend(batch)
                if len(batch)<500:return out
        with self.store.db() as db:return [json.loads(x[0]) for x in db.execute(f'select data from {table} where user_id=?',(uid,))]

    def owned_items(self,uid,ids):
        ids=sorted(str(i) for i in ids)
        if len(set(ids))!=len(ids):raise HTTPException(422,'Choose each item only once.')
        items=[self.repository.get_item(i,uid) for i in ids]
        if any(i is None or i.user_id!=uid for i in items):raise HTTPException(404,'One or more items are unavailable.')
        return ids,items

    @staticmethod
    def composition_signature(ids):
        return hashlib.sha256(','.join(sorted(str(i) for i in ids)).encode()).hexdigest()

    def disliked_signatures(self,uid):
        try:
            rows=self.rows('user_outfit_feedback_state',uid)
        except Exception:
            # Rolling deployment: reads remain available until migration 013 is applied.
            return set()
        return {row['composition_signature'] for row in rows if row.get('state')=='disliked'}

    def liked_signatures(self,uid):
        try:
            rows=self.rows('user_outfit_feedback_state',uid)
        except Exception:
            return set()
        # Read legacy state during rolling migration; new writes always use liked.
        return {row['composition_signature'] for row in rows if row.get('state') in {'liked','adopted'}}

    def save(self,uid,payload):
        ids,items=self.owned_items(uid,payload.item_ids)
        oid=str(uuid5(NAMESPACE_URL,'personal-outfit:'+uid+':'+','.join(ids)))
        row={'id':oid,'user_id':uid,'item_ids':ids,'title':payload.title,'created_at':datetime.now(timezone.utc).isoformat(),
             'feature_snapshot':snapshot_items(items)}
        if hasattr(self.store,'client'):
            row=self.store.client.rpc('save_personal_outfit',{'p_id':oid,'p_user':uid,'p_items':ids,'p_title':payload.title}).execute().data
        else:
            with self.store.db() as db:
                inserted=db.execute('insert or ignore into personal_outfits values (?,?,?)',(oid,uid,json.dumps(row))).rowcount
            if inserted:TasteProfileService(self.store).mark_source(uid)
        return self.dto(row,items)

    def dto(self,row,items):
        return OutfitDTO(id=row['id'],items=items,aesthetic_score=None,structural_reason='Saved by you',aesthetic_reason=row['title'],source='personal',visual_review_status='pending')

    def list(self,uid,anchor=None):
        items={i.id:i for i in self.repository.list_items_for_outfits(uid)}
        return [self.dto(r,[items[i] for i in r['item_ids']]) for r in self.rows('personal_outfits',uid)
                if (not anchor or str(anchor).lower() in r['item_ids']) and all(i in items for i in r['item_ids'])]

    def record_wear(self,uid,payload):
        _,items=self.owned_items(uid,payload.item_ids)
        ids=[str(item_id) for item_id in payload.item_ids]
        if payload.worn_at.tzinfo is None:raise HTTPException(422,'Wear time must include a timezone.')
        if payload.worn_at>datetime.now(timezone.utc)+timedelta(minutes=1):raise HTTPException(422,'Wear time cannot be in the future.')
        wear_date=payload.wear_date or payload.worn_at.date()
        row={'id':str(payload.id),'user_id':uid,'item_ids':ids,'worn_at':payload.worn_at.astimezone(timezone.utc).isoformat(),
             'wear_date':wear_date.isoformat(),'feature_snapshot':snapshot_items(items)}
        if hasattr(self.store,'client'):
            return self.store.client.rpc('set_today_outfit',{'p_id':row['id'],'p_user':uid,'p_items':ids,
                'p_worn_at':row['worn_at'],'p_wear_date':row['wear_date']}).execute().data
        with self.store.db() as db:
            old=db.execute('select data from outfit_wear_events where id=?',(row['id'],)).fetchone()
            if old and json.loads(old[0])!=row:raise HTTPException(409,'Wear event identity conflict.')
            key=uid+':'+row['wear_date']
            current=db.execute('select event_id from outfit_daily_selections where key=?',(key,)).fetchone()
            if current and current[0]!=row['id']:
                db.execute('delete from outfit_wear_events where id=? and user_id=?',(current[0],uid))
            inserted=db.execute('insert or ignore into outfit_wear_events values (?,?,?)',(row['id'],uid,json.dumps(row))).rowcount
            db.execute('insert into outfit_daily_selections values (?,?,?,?) on conflict(key) do update set event_id=excluded.event_id',
                       (key,uid,row['id'],row['wear_date']))
        if inserted:TasteProfileService(self.store).mark_source(uid)
        return row

    def undo_wear(self,uid,event_id):
        if hasattr(self.store,'client'):
            self.store.client.rpc('cancel_today_outfit',{'p_id':event_id,'p_user':uid}).execute()
        else:
            with self.store.db() as db:
                existed=db.execute('select 1 from outfit_wear_events where user_id=? and id=?',(uid,event_id)).fetchone()
                db.execute('delete from outfit_daily_selections where user_id=? and event_id=?',(uid,event_id))
                db.execute('delete from outfit_wear_events where user_id=? and id=?',(uid,event_id))
            if existed:TasteProfileService(self.store).mark_source(uid)

    def wear_status(self,uid,item_ids,wear_date):
        events=self.rows('outfit_wear_events',uid)
        signature=self.composition_signature(item_ids) if item_ids else None
        exact=[e for e in events if signature and self.composition_signature(e['item_ids'])==signature]
        latest=max((datetime.fromisoformat(e['worn_at'].replace('Z','+00:00')) for e in exact),default=None)
        if hasattr(self.store,'client'):
            selected=(self.store.client.table('outfit_daily_selections').select('wear_event_id')
                      .eq('user_id',uid).eq('wear_date',wear_date.isoformat()).limit(1).execute().data or [])
            event_id=selected[0]['wear_event_id'] if selected else None
        else:
            with self.store.db() as db:
                selected=db.execute('select event_id from outfit_daily_selections where key=?',
                                    (uid+':'+wear_date.isoformat(),)).fetchone()
            event_id=selected[0] if selected else None
        event=next((e for e in events if e['id']==event_id),None)
        items=[] if not event else [self.repository.get_item(i,uid) for i in event['item_ids']]
        items=[item for item in items if item is not None]
        return WearStatus(selected_today=WearEvent.model_validate(event) if event else None,
                          selected_today_items=items,latest_worn_at=latest,
                          liked=bool(signature and signature in self.liked_signatures(uid)))

    def record_feedback(self,uid,payload):
        ids,items=self.owned_items(uid,payload.item_ids)
        if not {str(item) for item in payload.target_item_ids} <= set(ids):
            raise HTTPException(422,'Feedback target items must belong to this outfit.')
        signature=self.composition_signature(ids)
        row={**payload.model_dump(mode='json'),'user_id':uid,'item_ids':ids,
             'composition_signature':signature,'created_at':datetime.now(timezone.utc).isoformat(),
             'feature_snapshot':snapshot_items(items,payload.context)}
        if hasattr(self.store,'client'):
            return self.store.client.rpc('record_outfit_feedback',{
                'p_event':row
            }).execute().data
        key=uid+':'+signature
        with self.store.db() as db:
            old=db.execute('select data from outfit_feedback_events where id=?',(str(payload.id),)).fetchone()
            if old:
                prior=json.loads(old[0])
                if {k:v for k,v in prior.items() if k!='created_at'}!={k:v for k,v in row.items() if k!='created_at'}:
                    raise HTTPException(409,'Feedback event identity conflict.')
                row=prior
            db.execute('insert or ignore into outfit_feedback_events values (?,?,?)',
                       (str(payload.id),uid,json.dumps(row)))
            state={'user_id':uid,'composition_signature':signature,'state':payload.action,
                   'latest_event_id':str(payload.id),'updated_at':row['created_at']}
            db.execute('insert into user_outfit_feedback_state values (?,?,?) on conflict(key) do update set data=excluded.data',
                       (key,uid,json.dumps(state)))
        if not old:TasteProfileService(self.store).mark_source(uid)
        return row
