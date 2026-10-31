import json
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import pytest
from app.outfits.runs import usage_fields, tracked_call, run_manifest
from test_outfit_library import setup, run_all


def test_run_dedup_and_one_generation_charge_per_call(setup):
    uid,top,bottom,lib,p=setup
    lib.build(uid)
    lib.build(uid)
    assert len(lib.store.run_report(uid))==1
    run_all(lib)
    report=lib.store.run_report(uid)[0]
    assert report['total_jobs']==2
    assert report['call_count']==3  # Two anchor generations, one shared evaluation.
    assert report['unique_results']==1
    assert report['unknown_cost_calls']==3  # Stub supplies no usage; not zero dollars.
    with lib.store.db() as db:
        saved=json.loads(db.execute('select data from outfits').fetchone()[0])['payload']
        assert 'config' not in saved and 'generation_usage' not in saved
        assert saved['run_id']==report['id']
    # Legacy exporters can still retrieve the immutable config.
    assert lib.store.evaluations(uid)[0]['payload']['config']['generation_model']==lib.config.generation_model


def test_usage_cached_tokens_cost_and_unknown():
    pricing={'input_per_million':2,'cached_input_per_million':1,'output_per_million':8}
    fields=usage_fields({'input_tokens':1000,'output_tokens':100,'input_tokens_details':{'cached_tokens':500}},pricing)
    assert Decimal(fields['estimated_cost_usd'])==Decimal('0.0023')
    assert usage_fields({},pricing)['estimated_cost_usd'] is None
    assert usage_fields({'input_tokens':100,'output_tokens':5},None)['estimated_cost_usd'] is None


def test_failure_and_interrupted_call_not_zero_cost(setup):
    uid,top,_,lib,_=setup
    lib.build(uid,top.id);job=lib.store.claim(lib.config)
    run=lib.store.ensure_job_run(job,run_manifest(uid,[job],lib.config))
    def fail():raise TimeoutError('private provider response')
    with pytest.raises(TimeoutError):tracked_call(lib.store,job,run,'generation','test',fail)
    lib.store.start_call({'id':'interrupted','run_id':run['id'],'job_id':job['id'],'user_id':uid,
                          'attempt':1,'lease_token':job['lease_token'],'status':'running','stage':'generation','model':'test'})
    lib.store.finish(job,'failed')
    lib.store.recover_calls()
    with lib.store.db() as db:
        calls=[json.loads(r[0]) for r in db.execute('select data from outfit_model_calls')]
    assert {c['status'] for c in calls}=={'failed','unknown'}
    assert all(c.get('estimated_cost_usd') is None for c in calls)
    assert 'private provider response' not in json.dumps(calls)


def test_retention_is_preview_first_and_pins_protect(setup):
    uid,top,_,lib,p=setup
    old_generate=p.generate
    p.generate=lambda *args:(old_generate(*args)[0],{'input_tokens':10,'output_tokens':20})
    lib.build(uid,top.id);run_all(lib)
    rid=lib.store.run_report(uid)[0]['id']
    with lib.store.db() as db:
        for cid,data in db.execute('select id,data from outfit_model_calls').fetchall():
            call=json.loads(data);call['finished_at']=(datetime.now(timezone.utc)-timedelta(days=200)).isoformat()
            db.execute('update outfit_model_calls set data=? where id=?',(json.dumps(call),cid))
    assert lib.store.compact_usage(uid)==1
    assert lib.store.compact_usage(uid)==1  # Preview changes nothing.
    assert lib.store.pin_run(uid,rid,'Professor comparison')
    assert lib.store.compact_usage(uid,True)==0
    assert lib.store.compact_usage('another-user',True)==0
    assert lib.store.run_report(uid)[0]['unique_results']==1


def test_multiple_outputs_do_not_duplicate_generation_usage(setup):
    from uuid import uuid4
    from app.outfits.models import Proposal, Proposals
    uid,top,bottom,lib,p=setup
    other=bottom.model_copy(update={'id':str(uuid4())});lib.repository.add_item(other)
    p.generate=lambda *args:(Proposals(outfits=[Proposal(item_ids=[top.id,b.id],reason='candidate') for b in [bottom,other]]),{'input_tokens':100,'output_tokens':20})
    lib.build(uid,top.id);run_all(lib)
    report=lib.store.run_report(uid)[0]
    assert report['call_count']==3 and report['unique_results']==2
    assert report['input_tokens']==100 and report['output_tokens']==20
    with lib.store.db() as db:
        calls=[json.loads(r[0]) for r in db.execute('select data from outfit_model_calls')]
    assert sum(c['stage']=='generation' for c in calls)==1


def test_projection_tracks_actual_audit_sources(setup):
    from test_outfit_library import Signer
    uid,top,_,lib,_=setup
    lib.build(uid,top.id);run_all(lib)
    provenance={}
    result=lib._records_list(uid,Signer(),'',provenance=provenance)
    assert len(result.outfits)==1
    assert provenance[result.outfits[0].id]=={lib.store.evaluations(uid)[0]['id']}


def test_late_response_repairs_unknown_billing(setup):
    uid,top,_,lib,_=setup
    lib.build(uid,top.id);job=lib.store.claim(lib.config)
    run=lib.store.ensure_job_run(job,run_manifest(uid,[job],lib.config))
    lib.store.start_call({'id':'late','run_id':run['id'],'job_id':job['id'],'user_id':uid,
        'attempt':1,'lease_token':job['lease_token'],'status':'running','stage':'generation','model':'test'})
    lib.store.finish(job,'failed');lib.store.recover_calls()
    lib.store.finish_call('late',{'status':'succeeded','input_tokens':10,'output_tokens':5,'estimated_cost_usd':'0.01'})
    assert lib.store.run_report(uid)[0]['unknown_cost_calls']==0
