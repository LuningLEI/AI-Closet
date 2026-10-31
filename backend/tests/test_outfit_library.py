from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from app.models.domain import ClothingItemRecord
from app.outfits.config import load_config
from app.outfits.models import (Evaluation, OptionalLayerReview, Proposal, Proposals,
                                VisualChecks, VisualCriterion, VisualReview)
from app.outfits.service import OutfitLibrary
from app.outfits.store import LocalOutfitStore

class Provider:
    def __init__(self, ids):self.ids=ids;self.evaluations=0;self.generations=0
    def generate(self, anchor, catalog):
        self.generations+=1
        return Proposals(outfits=[Proposal(item_ids=self.ids,reason='candidate')]),{}
    def evaluate(self, items):
        self.evaluations+=1
        checks = VisualChecks(**{name: VisualCriterion(verdict='pass', reason='valid')
                                 for name in VisualChecks.model_fields})
        return VisualReview(core=checks, full=checks,
            optional_layering=OptionalLayerReview(verdict='not_applicable', reason='No optional layer.')),{}

class Signer:
    def items(self,items,base_url):return items

@pytest.fixture
def setup(repository,tmp_path):
    uid=str(uuid4())
    top=ClothingItemRecord(id=str(uuid4()),user_id=uid,image_url='https://example.test/top',image_path='top.jpg',category='Tops',recognition_status='complete')
    bottom=ClothingItemRecord(id=str(uuid4()),user_id=uid,image_url='https://example.test/bottom',image_path='bottom.jpg',category='Bottoms',recognition_status='complete')
    repository.add_item(top);repository.add_item(bottom)
    store=LocalOutfitStore(tmp_path/'outfits.sqlite3');config=load_config().model_copy(update={'require_shoes':False,'accessory_pipeline':False,'footwear_pipeline':False})
    provider=Provider([top.id,bottom.id])
    return uid,top,bottom,OutfitLibrary(repository,store,config,provider),provider

def run_all(lib):
    while job:=lib.store.claim(lib.config):lib.process(job)

def test_anchor_union_dedup_cache_filter_and_idempotent_build(setup):
    uid,top,bottom,lib,p=setup
    assert lib.build(uid)['queued']==2
    assert lib.build(uid)['queued']==0
    run_all(lib)
    assert p.evaluations==1 and len(lib.store.evaluations(uid))==1
    result=lib.list(uid,Signer(),'')
    assert result.total==1 and result.jobs=={'complete':2}
    assert lib.list(uid,Signer(),'',top.id).total==1
    assert lib.list(uid,Signer(),'',bottom.id).total==1
    assert lib.list(uid,Signer(),'',str(uuid4())).total==0
    assert lib.list(str(uuid4()),Signer(),'').total==0

def test_new_item_incremental_and_changes_hide_stale_outfits(setup):
    uid,top,bottom,lib,p=setup
    lib.build(uid);run_all(lib)
    lib.repository.add_item(bottom.model_copy(update={'id':str(uuid4()),'image_path':'new.jpg'}))
    assert lib.sync(uid)==1
    lib.repository.update_item(top.id,{'color':'Blue'},uid)
    assert lib.list(uid,Signer(),'').total==0 and lib.sync(uid)==1
    lib.repository.delete_item(bottom.id,uid)
    assert lib.list(uid,Signer(),'').total==0

def test_garment_occasion_and_season_changes_invalidate_library(setup):
    uid,top,bottom,lib,p=setup
    lib.build(uid);run_all(lib)
    lib.repository.update_item(top.id,{'occasion':'Work','season':'Winter'},uid)
    assert lib.sync(uid)==1 and lib.list(uid,Signer(),'').total==0
    lib.config=lib.config.model_copy(update={'evaluation_text':lib.config.evaluation_text+'\nNew rubric.'})
    assert lib.list(uid,Signer(),'').total==0 and lib.sync(uid)==2

@pytest.mark.parametrize('kind',['foreign','missing_anchor','duplicate','invalid_structure'])
def test_invalid_candidates_never_call_evaluator(setup,kind):
    uid,top,bottom,lib,p=setup
    other=top.model_copy(update={'id':str(uuid4()),'user_id':str(uuid4())});lib.repository.add_item(other)
    p.ids={'foreign':[top.id,other.id],'missing_anchor':[bottom.id],'duplicate':[top.id,bottom.id,bottom.id],'invalid_structure':[top.id]}[kind]
    lib.build(uid,top.id);run_all(lib)
    assert p.evaluations==0 and lib.list(uid,Signer(),'').total==0

def test_mutation_during_model_call_discards_result(setup):
    uid,top,bottom,lib,p=setup;original=p.evaluate
    def evaluate(items):
        lib.repository.update_item(bottom.id,{'image_path':'replaced.jpg'},uid)
        return original(items)
    p.evaluate=evaluate;lib.build(uid,top.id);run_all(lib)
    assert not lib.store.evaluations(uid) and lib.store.jobs(uid)[0]['status']=='queued'

def test_worker_claim_is_exclusive_and_fenced(setup):
    uid,top,bottom,lib,p=setup;lib.build(uid,top.id)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:lib.store.claim(lib.config),range(2)))
    claimed=[r for r in results if r];assert len(claimed)==1;old=claimed[0]
    with lib.store.db() as db:
        data=json.loads(db.execute('select data from jobs').fetchone()[0]);data['lease_until']='2000-01-01T00:00:00+00:00'
        db.execute('update jobs set data=?',(json.dumps(data),))
    new=lib.store.claim(lib.config);assert new['lease_token']!=old['lease_token']
    lib.store.finish(old,'complete');assert lib.store.jobs(uid)[0]['status']=='processing'
    lib.store.finish(new,'complete');assert lib.store.jobs(uid)[0]['status']=='complete'

def test_failure_no_fake_pass_and_retry_limit(setup):
    uid,top,bottom,lib,p=setup;lib.config=lib.config.model_copy(update={'max_attempts':1})
    def fail(*args):raise RuntimeError('model failure')
    p.evaluate=fail;lib.build(uid,top.id)
    with pytest.raises(RuntimeError):lib.process(lib.store.claim(lib.config))
    assert lib.store.jobs(uid)[0]['status']=='failed' and not lib.store.evaluations(uid)
    assert lib.store.claim(lib.config) is None
    lib.build(uid,top.id,retry_failed=True);assert lib.store.claim(lib.config) is not None

def test_null_aesthetics_and_no_structure_fail_admission(setup):
    lib=setup[3]
    assert not lib.passes(Evaluation(structurally_wearable='cannot_judge',aesthetic_score=None,structural_reason='',aesthetic_reason='',issues=[]))
    assert not lib.passes(Evaluation(structurally_wearable='no',aesthetic_score=5,structural_reason='',aesthetic_reason='',issues=[]))

def test_outfit_routes_user_scope_and_build_does_not_run_models(setup,monkeypatch):
    from app.api import outfit_routes, routes
    from app.outfits.personal import PersonalOutfits, OutfitFeedbackRequest
    from app.main import app
    uid,top,bottom,lib,p=setup
    monkeypatch.setattr(outfit_routes,'library',lambda:lib)
    monkeypatch.setattr(routes,'mutation_user_id',lambda request:uid)
    monkeypatch.setattr(routes,'current_user_id',lambda request:uid)
    monkeypatch.setattr(routes,'signing_service',Signer())
    feedback=PersonalOutfits(lib.repository,lib.store)
    monkeypatch.setattr(outfit_routes,'personal',lambda:feedback)
    client=TestClient(app)
    assert client.post('/api/v1/outfits/build',json={}).json()['queued']==2 and p.generations==0
    run_all(lib);assert client.get('/api/v1/outfits').json()['total']==1
    assert client.get('/api/v1/outfits?liked_only=true').json()['total']==0
    feedback.record_feedback(uid,OutfitFeedbackRequest(id=uuid4(),outfit_id=None,
        item_ids=[top.id,bottom.id],action='liked',surface='library'))
    liked=client.get('/api/v1/outfits?liked_only=true').json()
    assert liked['total']==1 and liked['outfits'][0]['liked'] is True
    monkeypatch.setattr(routes,'current_user_id',lambda request:str(uuid4()))
    assert client.get('/api/v1/outfits').json()['total']==0
    assert client.get('/api/v1/outfits?limit=1000').status_code==422


def test_focused_build_does_not_enroll_whole_wardrobe(setup):
    uid,top,bottom,lib,p=setup
    result=lib.build(uid,top.id)
    assert result['queued']==1
    assert not lib.store.enrolled(uid)
    assert len(lib.store.jobs(uid))==1
    run_all(lib)
    assert lib.list(uid,Signer(),'').total==1
    assert lib.build(uid)['queued']==1
    assert lib.store.enrolled(uid)


def test_addons_are_manual_only_anchors_but_remain_outfit_candidates(setup):
    uid,top,bottom,lib,p=setup
    addons=[
        top.model_copy(update={'id':str(uuid4()),'category':'Shoes','subtype':'Flats','image_path':'shoes.jpg'}),
        top.model_copy(update={'id':str(uuid4()),'category':'Bags','subtype':'Shoulder Bag','image_path':'bag.jpg'}),
        top.model_copy(update={'id':str(uuid4()),'category':'Accessories','subtype':'Hat','image_path':'hat.jpg'}),
    ]
    for item in addons:lib.repository.add_item(item)

    assert lib.build(uid)['queued']==2
    assert {job['anchor_item_id'] for job in lib.store.jobs(uid)}=={top.id,bottom.id}
    assert {item.id for item in lib.items(uid).values()}=={top.id,bottom.id,*(item.id for item in addons)}

    # An explicit per-item Generate Outfit action bypasses the automatic filter
    # for every add-on category.
    for item in addons:
        assert lib.build(uid,item.id)['queued']==1
    assert {item.id for item in addons} <= {job['anchor_item_id'] for job in lib.store.jobs(uid)}


def test_core_outfits_group_optional_coats_and_filter_membership(setup):
    from app.outfits.models import VisualReview, VisualChecks, VisualCriterion, OptionalLayerReview
    uid,top,bottom,lib,p=setup
    lib.config=load_config().model_copy(update={'require_shoes':False,'accessory_pipeline':False,'footwear_pipeline':False})  # Pre-footwear fixtures
    checks=VisualChecks(**{k:VisualCriterion(verdict='pass',reason='Visually compatible') for k in VisualChecks.model_fields})
    p.evaluate=lambda items:(VisualReview(core=checks,full=checks,optional_layering=OptionalLayerReview(verdict='clear_improvement' if len(items)>2 else 'not_applicable',reason='The fitted jacket visibly improves proportions.')), {})
    coats=[top.model_copy(update={'id':str(uuid4()),'category':'Outerwear','subtype':'Jacket','image_path':f'coat-{n}.jpg'}) for n in range(2)]
    for coat in coats:lib.repository.add_item(coat)
    def generate(anchor,catalog):
        return Proposals(outfits=[Proposal(item_ids=[top.id,bottom.id],reason='base')]+[
            Proposal(item_ids=[top.id,bottom.id,coat.id],reason='optional coat') for coat in coats]),{}
    p.generate=generate
    lib.build(uid,top.id);run_all(lib)
    response=lib.list(uid,Signer(),'')
    assert response.total==1
    outfit=response.outfits[0]
    assert {i.id for i in outfit.items}=={top.id,bottom.id}
    assert len(outfit.optional_additions)==2
    assert {i.id for variant in outfit.optional_additions for i in variant.items}=={i.id for i in coats}
    filtered=lib.list(uid,Signer(),'',coats[0].id)
    assert filtered.total==1 and filtered.outfits[0].id==outfit.id
    assert len(filtered.outfits[0].optional_additions)==1
    assert filtered.outfits[0].optional_additions[0].items[0].id==coats[0].id


def test_explicit_compatibility_rules_apply_even_without_rating_filter(setup):
    uid,top,bottom,lib,p=setup
    lib.repository.update_item(top.id,{'pattern':'Floral'},uid)
    lib.repository.update_item(bottom.id,{'pattern':'Striped'},uid)
    lib.build(uid,top.id);run_all(lib)
    assert p.evaluations==0 and lib.list(uid,Signer(),'').total==0
    lib.repository.update_item(bottom.id,{'pattern':'Solid'},uid)
    lib.build(uid,bottom.id);run_all(lib)
    assert lib.list(uid,Signer(),'').total==1


def test_catalog_prioritizes_white_shirt_for_black_pencil_skirt(setup):
    uid,top,bottom,lib,p=setup
    bottom=bottom.model_copy(update={'subtype':'Pencil Skirt','color':'Black','style':'Business'})
    white=top.model_copy(update={'subtype':'Button-down Shirt','color':'White','pattern':'Solid','style':'Classic'})
    rivals=[top.model_copy(update={'id':str(uuid4()),'color':'Pink','subtype':'Blouse','style':'Business'}) for _ in range(30)]
    lib.config=lib.config.model_copy(update={'catalog_limit':4})
    catalog=lib.select_catalog(bottom,[bottom,white]+rivals)
    assert catalog[0].id==bottom.id and catalog[1].id==white.id


def test_concurrent_worker_claims_distinct_anchors_and_deduplicates_results(setup):
    import threading
    from workers.outfits import process_next
    uid,top,bottom,lib,p=setup
    lib.build(uid)
    barrier=threading.Barrier(2)
    claims=[]
    lock=threading.Lock()
    class ConcurrentProvider(Provider):
        def generate(self,anchor,catalog):
            with lock:claims.append(anchor.id)
            barrier.wait(timeout=5)
            return super().generate(anchor,catalog)
    def run():
        independent_store=LocalOutfitStore(lib.store.path)
        independent_lib=OutfitLibrary(lib.repository,independent_store,lib.config,ConcurrentProvider([top.id,bottom.id]))
        return process_next(independent_lib)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:run(),range(2)))
    assert results==[True,True] and set(claims)=={top.id,bottom.id}
    assert len(lib.store.evaluations(uid))==1
    assert lib.list(uid,Signer(),'').total==1
    assert lib.progress(uid)=={'complete':2}


def test_purpose_rule_refilters_saved_results_without_rebuilding_or_deleting(setup):
    uid,top,bottom,lib,p=setup
    lib.config=lib.config.model_copy(update={
        'compatibility_rules':lib.config.compatibility_rules.model_copy(update={'block_purpose_conflicts':False}),
    })
    lib.repository.update_item(top.id,{'category':'Activewear','subtype':'Workout Top'},uid)
    lib.repository.update_item(bottom.id,{'subtype':'Pencil Skirt'},uid)
    lib.build(uid,top.id);run_all(lib)
    assert lib.list(uid,Signer(),'').total==1
    key=lib.config.generation_key
    lib.config=lib.config.model_copy(update={'compatibility_rules':
        lib.config.compatibility_rules.model_copy(update={'block_purpose_conflicts':True})})
    assert lib.config.generation_key==key and lib.sync(uid,top.id)==0
    assert lib.list(uid,Signer(),'').total==0
    assert len(lib.store.evaluations(uid))==1 and p.evaluations==1
