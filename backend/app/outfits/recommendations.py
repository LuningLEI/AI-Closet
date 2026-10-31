"""Rank saved outfits; never generate fresh garment combinations here."""
import hashlib
from pathlib import Path
from datetime import datetime,timezone
from app.outfits.config import load_config
from app.outfits.store import build_store
from app.outfits.service import OutfitLibrary
from app.outfits.personal import PersonalOutfits
from app.outfits.compatibility import compatibility_issues
from app.outfits.service import structurally_valid
from app.services.recommendation.rules import recommendation_slot,profile_memory_text
from app.services.embedding_service import recommendation_context_text
from app.services.occasion_support import occasion_for_display
from app.services.occasion_thresholds import resolve_thresholds
from app.services.taxonomy import merge_preferences
from app.services.taste_profile_service import TasteProfileService
from app.services.taste_profile import EXPLORATION_RATE
from pydantic import BaseModel,Field,model_validator

class WearPolicy(BaseModel):
    wear_exclusion_days: float = Field(default=2,ge=0)
    wear_penalty_points: float = Field(default=40,ge=0)
    wear_penalty_half_life_days: float = Field(default=3,gt=0)
    wear_penalty_cutoff_days: float = Field(default=14,gt=0)
    @model_validator(mode='after')
    def valid_window(self):
        if self.wear_penalty_cutoff_days<=self.wear_exclusion_days:raise ValueError('Cutoff must exceed exclusion period')
        return self

def load_policy():
    return WearPolicy.model_validate_json(Path(__file__).with_name('recommendation_policy.json').read_text())

def wear_effect(items,events,policy,now=None):
    now=now or datetime.now(timezone.utc)
    ids={i.id for i in items};last=[]
    for e in events:
        if ids.intersection(e['item_ids']):
            t=datetime.fromisoformat(e['worn_at'].replace('Z','+00:00'))
            if t.tzinfo is None:raise ValueError('Wear timestamp requires timezone')
            last.append(t)
    if not last:return False,0.0
    age=max(0,(now-max(last)).total_seconds()/86400)
    if age<policy.wear_exclusion_days:return True,policy.wear_penalty_points
    if age>=policy.wear_penalty_cutoff_days:return False,0.0
    return False,policy.wear_penalty_points*2**(-(age-policy.wear_exclusion_days)/policy.wear_penalty_half_life_days)

class SavedCandidate:
    def __init__(self,oid,items):
        self.identifier=oid;self.items=items
        for role,attr in [('Tops','top'),('Bottoms','bottom'),('FullBody','full_body'),('Shoes','shoes'),('Outerwear','outerwear'),('Accessories','accessory')]:
            setattr(self,attr,next((i for i in items if recommendation_slot(i.category,i.subtype)==role),None))

class IdentitySigner:
    def items(self,items,base_url):return items

def recommend_library(repository,engine,uid,context,preferences):
    store=build_store(repository);lib=OutfitLibrary(repository,store,load_config())
    personal=PersonalOutfits(repository,store)
    taste=TasteProfileService(store).ensure_current(uid)
    outfits=[];offset=0
    if hasattr(store,'projected_page'):
        while True:
            page=lib.list(uid,IdentitySigner(),'',offset=offset,limit=100)
            outfits.extend(page.outfits)
            if page.next_offset is None:break
            offset=page.next_offset
    else:
        outfits=lib._records_list(uid,IdentitySigner(),'',limit=10_000_000).outfits+personal.list(uid)
    current={i.id:i for i in repository.list_items_for_recommendation(uid)} if outfits else {}
    preferences=merge_preferences(preferences);thresholds=resolve_thresholds(preferences)
    events=personal.rows('outfit_wear_events',uid);policy=load_policy()
    disliked=personal.disliked_signatures(uid)
    candidates=[];seen=set()
    for outfit in outfits:
        if outfit.source!='personal' and outfit.visual_review_status!='passed':continue
        sets=[outfit.items]+[outfit.items+v.items for v in outfit.optional_additions if v.visual_review_status=='passed']
        for members in sets:
            if any(i.id not in current for i in members):continue
            members=list({i.id:current[i.id] for i in members}.values())
            # A personal outfit is an explicit user decision. Preserve and rank it
            # exactly as saved; generated outfits still obey system validation.
            if (outfit.source != 'personal'
                    and (not structurally_valid(members, require_shoes=lib.config.require_shoes)
                         or compatibility_issues(members, lib.config.compatibility_rules))):
                continue
            signature=tuple(sorted(i.id for i in members))
            if personal.composition_signature(signature) in disliked:continue
            if signature in seen:continue
            seen.add(signature)
            blocked,penalty=wear_effect(members,events,policy)
            if blocked:continue
            candidate=SavedCandidate(outfit.id,[occasion_for_display(i,thresholds) for i in members])
            candidates.append((candidate,penalty,outfit.source=='personal'))
    if not candidates:return []
    vector=None
    if any(i.semantic_vector for c,_,_ in candidates for i in c.items):
        vector=engine.embedding_service.create_embedding(recommendation_context_text(context)+' '+profile_memory_text(preferences, context.occasion))
    results=[]
    for candidate,penalty,trusted_user_outfit in candidates:
        result=engine.scorer.score(
            candidate,
            context,
            vector,
            preferences,
            trusted_user_outfit=trusted_user_outfit,
            taste_profile=taste,
        )
        if result is None:continue
        result.original_score=round(result.score-result.personalization_score,2)
        result.wear_penalty=round(penalty,2)
        result.score=round(max(0,result.score-penalty),2)
        # Distinguish optional variants while preserving the library identity.
        result.outfit_id=candidate.identifier
        result.id=candidate.identifier+':'+','.join(sorted(i.id for i in candidate.items))
        results.append(result)
    results.sort(key=lambda r:(-r.score,r.id))
    memory=taste.get('generation_memory') or {}
    if memory.get('evidence_threshold_met') and len(results)>context.limit and context.limit>=5:
        quota=max(1,round(context.limit*memory.get('exploration_rate',EXPLORATION_RATE)))
        head=results[:max(0,context.limit-quota)]
        rest=results[max(0,context.limit-quota):]
        seed=f"{uid}:{datetime.now(timezone.utc).date()}:{context.occasion}"
        rest.sort(key=lambda row:hashlib.sha256(f"{seed}:{row.id}".encode()).hexdigest())
        results=head+rest[:quota]
    return engine._diversify(results,context.limit)[:context.limit]
