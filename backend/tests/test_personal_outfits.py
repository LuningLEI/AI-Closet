from uuid import uuid4
from datetime import datetime,timezone,timedelta
import pytest
from fastapi import HTTPException
from test_outfit_library import setup,Signer,run_all
from app.outfits.personal import PersonalOutfits,PersonalOutfitRequest,WearRequest,OutfitFeedbackRequest
from app.outfits.recommendations import (
    WearPolicy,
    policy_for_rotation,
    recommend_library,
    occasion_eligible_results,
    rotate_near_tied_results,
    stratified_score_rotation,
    temperature_eligible_results,
    wear_effect,
)
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


def test_replace_items_persists_one_override_and_shadows_generated_outfit(setup):
    uid,top,bottom,lib,_=setup
    lib.build(uid);run_all(lib)
    generated=lib.list(uid,Signer(),'').outfits[0]
    replacement=lib.repository.add_item(bottom.model_copy(
        update={'id':str(uuid4()),'image_path':'replacement.jpg','color':'Blue'}
    ))
    personal=PersonalOutfits(lib.repository,lib.store)

    first=personal.save(uid,PersonalOutfitRequest(
        item_ids=[top.id,replacement.id],replaces_outfit_id=generated.id,
    ))
    reopened=lib.list(uid,Signer(),'')
    assert reopened.total==1
    assert reopened.outfits[0].id==first.id
    assert reopened.outfits[0].source=='personal'
    assert reopened.outfits[0].replaces_outfit_id==generated.id
    assert {item.id for item in reopened.outfits[0].items}=={top.id,replacement.id}

    second=personal.save(uid,PersonalOutfitRequest(
        item_ids=[bottom.id,replacement.id],replaces_outfit_id=first.id,
    ))
    assert second.id==first.id
    assert len(personal.rows('personal_outfits',uid))==1
    assert {item.id for item in lib.list(uid,Signer(),'').outfits[0].items}=={
        bottom.id,replacement.id
    }


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


def test_rotation_levels_map_to_distinct_wear_policies(setup):
    _,top,_,_,_=setup;now=datetime.now(timezone.utc)
    event=[{'item_ids':[top.id],'worn_at':(now-timedelta(days=1)).isoformat()}]
    assert wear_effect([top],event,policy_for_rotation('repeat_freely'),now)==(False,0.0)
    assert wear_effect([top],event,policy_for_rotation('balanced'),now)[0] is True
    assert wear_effect([top],event,policy_for_rotation('more_variety'),now)[0] is True


def test_page_seed_rotates_only_near_tied_recommendations():
    class Result:
        def __init__(self, identifier, score):
            self.id=identifier
            self.score=score

    ranked=[Result(f'near-{index}',100-index*.2) for index in range(12)]
    ranked.append(Result('outside-quality-window',80))

    assert rotate_near_tied_results(ranked,'user',None,5)==ranked
    first=rotate_near_tied_results(ranked,'user','page-a',5)
    assert [row.id for row in first]==[
        row.id for row in rotate_near_tied_results(ranked,'user','page-a',5)
    ]
    pages={
        tuple(row.id for row in rotate_near_tied_results(ranked,'user',f'page-{index}',5)[:5])
        for index in range(10)
    }
    assert len(pages)>1
    assert all('outside-quality-window' not in page for page in pages)


def test_score_band_rotation_returns_four_high_one_middle_and_no_low():
    class Breakdown:
        weather_fit=20
    class Result:
        def __init__(self, index):
            self.id=f'outfit-{index}'
            self.score=100-index
            self.breakdown=Breakdown()
            self.missing_slots=[]

    ranked=[Result(index) for index in range(30)]
    page=stratified_score_rotation(ranked,'user','page-a',5)[:5]
    indexes=[int(row.id.rsplit('-',1)[1]) for row in page]
    assert sum(index < 10 for index in indexes)==4
    assert sum(10 <= index < 20 for index in indexes)==1
    assert sum(index >= 20 for index in indexes)==0
    assert [row.score for row in page] == sorted(
        [row.score for row in page], reverse=True
    )
    assert [row.id for row in page]==[
        row.id for row in stratified_score_rotation(ranked,'user','page-a',5)[:5]
    ]
    assert [row.id for row in page] != [
        row.id for row in stratified_score_rotation(ranked,'user','page-b',5)[:5]
    ]


def test_mild_weather_page_limits_repeated_short_lower_body_silhouettes():
    class Breakdown:
        weather_fit=20
    class Item:
        def __init__(self, identifier, subtype, length=None):
            self.id=identifier
            self.category='Bottoms'
            self.subtype=subtype
            self.length=length
    class Result:
        def __init__(self, index, subtype):
            self.id=f'outfit-{index}'
            self.score=100-index
            self.breakdown=Breakdown()
            self.missing_slots=[]
            self.items=[Item(f'bottom-{index}',subtype)]

    ranked=[
        Result(index,'Shorts' if index % 2 == 0 else 'Wide-leg Pants')
        for index in range(30)
    ]
    page=stratified_score_rotation(ranked,'user','mild-page',5,70)[:5]
    assert sum(row.items[0].subtype == 'Shorts' for row in page) <= 2
    assert len({row.items[0].id for row in page}) == 5


def test_temperature_gate_applies_before_score_band_sampling():
    class Breakdown:
        def __init__(self, weather_fit):self.weather_fit=weather_fit
    class Result:
        def __init__(self, identifier, weather_fit, missing_slots=None, items=None):
            self.id=identifier
            self.breakdown=Breakdown(weather_fit)
            self.missing_slots=missing_slots or []
            self.items=items or []
    class Item:
        def __init__(self, season):self.season=season

    rows=[
        Result('compatible',18),
        Result('weather-mismatch',8),
        Result('cold-without-layer',18,['outerwear']),
        Result('winter-only',18,items=[Item('Winter')]),
    ]
    assert [row.id for row in temperature_eligible_results(rows,60)] == [
        'compatible','cold-without-layer'
    ]
    assert [row.id for row in temperature_eligible_results(rows,85)] == [
        'compatible','cold-without-layer'
    ]
    assert [row.id for row in temperature_eligible_results(rows,40)] == [
        'compatible','winter-only'
    ]


def test_occasion_gate_prefers_direct_matches_and_rejects_wrong_core_items():
    class Item:
        def __init__(self, identifier, category, occasion):
            self.id=identifier
            self.category=category
            self.subtype='T-shirt' if category == 'Tops' else 'Trousers'
            self.occasion=occasion
    class Result:
        def __init__(self, identifier, top_occasion, bottom_occasion):
            self.id=identifier
            self.items=[
                Item(f'{identifier}-top','Tops',top_occasion),
                Item(f'{identifier}-bottom','Bottoms',bottom_occasion),
            ]

    rows=[
        Result('party','Party','Party'),
        Result('mixed','Party','Everyday'),
        Result('work','Work','Work'),
    ]
    assert [row.id for row in occasion_eligible_results(rows,'Party',5)] == ['party','mixed']
    assert [row.id for row in occasion_eligible_results(rows,'Work',5)] == ['work']


def test_occasion_gate_uses_everyday_only_as_safe_fallback_when_page_is_short():
    class Item:
        def __init__(self, identifier, occasion):
            self.id=identifier;self.category='Tops';self.subtype='T-shirt';self.occasion=occasion
    class Result:
        def __init__(self, identifier, occasion):self.id=identifier;self.items=[Item(identifier,occasion)]

    rows=[Result('direct','Travel'),Result('fallback','Everyday'),Result('wrong','Workout')]
    assert [row.id for row in occasion_eligible_results(rows,'Travel',5)] == ['direct','fallback']
    assert [row.id for row in occasion_eligible_results(rows,'Travel',1)] == ['direct']


def test_date_occasion_uses_everyday_pieces_to_complete_or_backfill_a_page():
    class Item:
        def __init__(self, identifier, occasion):
            self.id=identifier;self.category='Tops';self.subtype='Blouse';self.occasion=occasion
    class Result:
        def __init__(self, identifier, occasions):
            self.id=identifier;self.items=[Item(f'{identifier}-{index}',occasion) for index,occasion in enumerate(occasions)]

    rows=[
        Result('date-with-basic',['Date','Everyday']),
        Result('everyday-fallback',['Everyday','Everyday']),
        Result('work-only',['Work','Work']),
    ]
    assert [row.id for row in occasion_eligible_results(rows,'Date',5)] == [
        'date-with-basic','everyday-fallback'
    ]


def test_score_rotation_limits_variants_from_the_same_base_outfit():
    class Breakdown:
        weather_fit=20
    class Item:
        def __init__(self, identifier):
            self.id=identifier;self.category='Tops';self.subtype='T-shirt';self.length=None
    class Result:
        def __init__(self, index):
            self.id=f'variant-{index}';self.outfit_id='same-base' if index < 10 else f'base-{index}'
            self.score=100-index;self.breakdown=Breakdown();self.missing_slots=[]
            self.items=[Item(f'top-{index}')]

    page=stratified_score_rotation([Result(index) for index in range(30)],'user','page',5,60)[:5]
    assert sum(row.outfit_id == 'same-base' for row in page) <= 1


def test_score_rotation_avoids_repeating_one_outerwear_when_alternatives_exist():
    class Breakdown:
        weather_fit=20
    class Item:
        def __init__(self, identifier, category, subtype):
            self.id=identifier;self.category=category;self.subtype=subtype;self.length=None
    class Result:
        def __init__(self, index):
            self.id=f'outfit-{index}';self.score=100-index
            self.breakdown=Breakdown();self.missing_slots=[]
            self.items=[
                Item(f'top-{index}','Tops','T-shirt'),
                Item('repeated-coat' if index < 10 else f'coat-{index}','Outerwear','Jacket'),
            ]

    page=stratified_score_rotation([Result(index) for index in range(30)],'user','page',5,60)[:5]
    repeated=sum(
        item.id == 'repeated-coat'
        for row in page for item in row.items
    )
    assert repeated <= 1


def test_temperature_gate_uses_celsius_season_and_exposed_clothing_boundaries():
    class Breakdown:
        weather_fit=18
    class Item:
        def __init__(self, identifier, season, category, subtype, sleeve_length=None):
            self.id=identifier
            self.season=season
            self.category=category
            self.subtype=subtype
            self.sleeve_length=sleeve_length
            self.length=None
    class Result:
        def __init__(self, identifier, items):
            self.id=identifier
            self.items=items
            self.breakdown=Breakdown()
            self.missing_slots=[]

    winter=Result('winter',[Item('winter-pants','Winter','Bottoms','Trousers')])
    spring=Result('spring',[Item('spring-pants','Spring','Bottoms','Trousers')])
    summer_pants=Result('summer-pants',[Item('summer-pants','Summer','Bottoms','Trousers')])
    summer_tee=Result('summer-tee',[Item('tee','Spring, Summer','Tops','T-shirt','Short Sleeve')])
    summer_shorts=Result('summer-shorts',[Item('shorts','Spring, Summer','Bottoms','Shorts')])
    layered_tee=Result('layered-tee',[
        Item('tee-layer','Spring, Summer','Tops','T-shirt','Short Sleeve'),
        Item('jacket','Spring, Summer','Outerwear','Jacket','Long Sleeve'),
    ])
    season_rows=[winter,spring,summer_pants]
    exposed_rows=[summer_tee,summer_shorts,layered_tee]

    assert [row.id for row in temperature_eligible_results(season_rows,46.4)] == ['winter']
    assert [row.id for row in temperature_eligible_results(season_rows,53.6)] == ['spring']
    assert [row.id for row in temperature_eligible_results(season_rows,68)] == ['spring']
    assert [row.id for row in temperature_eligible_results(exposed_rows,73.4)] == [
        'layered-tee'
    ]
    assert [row.id for row in temperature_eligible_results(season_rows,75.2)] == [
        'summer-pants'
    ]
    assert [row.id for row in temperature_eligible_results(exposed_rows,80.6)] == [
        'summer-tee','summer-shorts','layered-tee'
    ]


def test_boundary_temperatures_probabilistically_mix_both_sides():
    class Breakdown:
        weather_fit=18
    class Item:
        def __init__(self, identifier, season, subtype='Trousers', sleeve_length=None):
            self.id=identifier
            self.season=season
            self.category='Tops' if subtype == 'T-shirt' else 'Bottoms'
            self.subtype=subtype
            self.sleeve_length=sleeve_length
            self.length=None
    class Result:
        def __init__(self, identifier, item):
            self.id=identifier
            self.items=[item]
            self.breakdown=Breakdown()
            self.missing_slots=[]

    winter=[Result(f'winter-{i}',Item(f'wi-{i}','Winter')) for i in range(200)]
    spring=[Result(f'spring-{i}',Item(f'sp-{i}','Spring')) for i in range(200)]
    at_ten=temperature_eligible_results(winter+spring,50,'ten-celsius')
    assert 70 <= sum(row.id.startswith('winter-') for row in at_ten) <= 130
    assert 70 <= sum(row.id.startswith('spring-') for row in at_ten) <= 130

    spring=[Result(f'spring22-{i}',Item(f'sp22-{i}','Spring')) for i in range(200)]
    summer=[Result(f'summer22-{i}',Item(f'su22-{i}','Summer')) for i in range(200)]
    at_twenty_two=temperature_eligible_results(spring+summer,71.6,'twenty-two-celsius')
    assert 70 <= sum(row.id.startswith('spring22-') for row in at_twenty_two) <= 130
    assert 70 <= sum(row.id.startswith('summer22-') for row in at_twenty_two) <= 130

    exposed=[
        Result(f'tee25-{i}',Item(f'tee-{i}','Spring, Summer','T-shirt','Short Sleeve'))
        for i in range(200)
    ]
    at_twenty_five=temperature_eligible_results(exposed,77,'twenty-five-celsius')
    assert 70 <= len(at_twenty_five) <= 130
    assert [row.id for row in at_twenty_five] == [
        row.id for row in temperature_eligible_results(exposed,77,'twenty-five-celsius')
    ]


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
