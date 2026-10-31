import json
import pytest
from app.outfits.config import load_config
from app.outfits.models import VisualReview, CurrentVisualReview, OptionalLayerReview, VisualChecks, VisualCriterion, Evaluation
from app.outfits.provider import VisionOutfitProvider
from test_outfit_library import setup, run_all, Signer


def review(core='pass', full='pass', optional=None):
    def checks(verdict):
        return VisualChecks(**{k:VisualCriterion(verdict=verdict,reason=k+' evidence') for k in VisualChecks.model_fields})
    return VisualReview(core=checks(core),full=checks(full), **({'optional_layering': OptionalLayerReview(verdict=optional,reason="Visible silhouette improvement")} if optional else {}))


def test_generation_and_review_use_images(setup):
    _,top,bottom,_,_=setup
    class Storage:
        def signed_image_url(self,*a,**kw):return 'https://example.test/photo'
    p=VisionOutfitProvider(load_config(),Storage())
    calls=[]
    def request(model,prompt,content,schema):
        calls.append((content,schema));return None,{}
    p.request=request
    p.generate(top,[top,bottom])
    assert sum(x['type']=='input_image' for x in calls[0][0])==2
    assert json.loads(calls[0][0][0]['text'])['maximum_outfits']==8
    labels=[json.loads(x['text']) for x in calls[0][0][1:] if x['type']=='input_text']
    assert {x['id'] for x in labels}=={top.id,bottom.id}
    assert all('color' in x and 'category' in x for x in labels)
    p.evaluate([top,bottom])
    assert sum(x['type']=='input_image' for x in calls[1][0])==2
    assert calls[1][1] is CurrentVisualReview
    schema=CurrentVisualReview.model_json_schema()
    assert set(schema['required'])=={'core','full','optional_layering'}


def test_generation_and_final_review_receive_eligible_taste(setup):
    _,top,bottom,_,_=setup
    class Storage:
        def signed_image_url(self,*a,**kw):return 'https://example.test/photo'
    p=VisionOutfitProvider(load_config(),Storage())
    p.taste_profile={
        'feature_weights': {}, 'feature_evidence': {},
        'free_text_summary': {'summary':'Prefers black and white'},
        'generation_memory': {'evidence_threshold_met':True,'preferred':['color:black'],
            'avoid':['pattern:floral'],'exploration_rate':.10}}
    calls=[]
    p.request=lambda model,prompt,content,schema:(calls.append((prompt,content,schema)) or (None,{}))
    p.generate_clothing(top,[top,bottom])
    generation=json.loads(calls[0][1][0]['text'])['learned_taste']
    assert generation['exploration_outfit_count']==1
    assert 'free_text_summary' in generation
    p.evaluate_batch([(1,[top,bottom])])
    review=json.loads(calls[1][1][0]['text'])
    assert review['learned_taste']['free_text_summary']['summary']=='Prefers black and white'
    assert 'actively compare' in calls[1][0]


def test_default_uses_only_visual_generation():
    config=load_config()
    assert config.pipeline_mode=='vision_then_visual'
    assert 'images' in config.generation_text
    assert 'NO images' not in config.generation_text
    assert config.pipeline_mode == 'vision_then_visual'


def test_new_review_replaces_previous_acceptance_without_deleting_history(setup):
    uid,top,bottom,lib,p=setup
    lib.build(uid,top.id);run_all(lib)
    assert lib.list(uid,Signer(),'').outfits[0].visual_review_status=='passed'
    p.evaluate=lambda items:(review(core='fail'),{})
    lib.config=lib.config.model_copy(update={'evaluation_text':lib.config.evaluation_text+'\nVersion 2.'})
    lib.build(uid,top.id);run_all(lib)
    assert lib.list(uid,Signer(),'').total==0
    assert len(lib.store.evaluations(uid))==2
    current=[r for r in lib.store.evaluations(uid) if r['evaluator_key']==lib.config.evaluator_key][0]
    assert current['payload']['visual_review']['core']['occasion']['verdict']=='fail'


def test_good_core_kept_when_optional_layer_fails(setup):
    from uuid import uuid4
    uid,top,bottom,lib,p=setup
    coat=top.model_copy(update={'id':str(uuid4()),'category':'Outerwear','subtype':'Jacket'})
    lib.repository.add_item(coat)
    p.ids=[top.id,bottom.id,coat.id]
    lib.config=load_config().model_copy(update={'require_shoes':False,'accessory_pipeline':False,'footwear_pipeline':False})  # Pre-footwear fixtures
    p.evaluate=lambda items:(review(full='fail'),{})
    lib.build(uid,top.id);run_all(lib)
    result=lib.list(uid,Signer(),'')
    assert result.total==1 and result.outfits[0].visual_review_status=='passed'
    assert not result.outfits[0].optional_additions
    assert lib.list(uid,Signer(),'',coat.id).total==0


def test_uncertainty_is_saved_but_not_admitted(setup):
    uid,top,bottom,lib,p=setup
    lib.config=load_config().model_copy(update={'require_shoes':False,'accessory_pipeline':False,'footwear_pipeline':False})  # Pre-footwear fixtures
    p.evaluate=lambda items:(review(core='uncertain'),{})
    lib.build(uid,top.id);run_all(lib)
    assert len(lib.store.evaluations(uid))==1
    assert lib.list(uid,Signer(),'').total==0
    assert lib.store.jobs(uid)[0]['stats']['passing']==0


@pytest.mark.parametrize('kind',['upper','lower'])
@pytest.mark.parametrize('verdict',[None,'uncertain','no_improvement','not_applicable','clear_improvement'])
def test_optional_layers_require_positive_visual_improvement(setup,kind,verdict):
    from uuid import uuid4
    uid,top,bottom,lib,p=setup
    if kind=='upper':
        extra=top.model_copy(update={'id':str(uuid4()),'category':'Outerwear','subtype':'Jacket'})
    else:
        lib.repository.update_item(bottom.id,{'recognition_tags':{'wearing_profile':{'lower_layer_role':'base','can_layer_under':True}}},uid)
        extra=bottom.model_copy(update={'id':str(uuid4()),'subtype':'Midi Skirt','recognition_tags':{'wearing_profile':{'lower_layer_role':'outer','can_layer_over':True}}})
    lib.repository.add_item(extra)
    p.ids=[top.id,bottom.id,extra.id]
    lib.config=load_config().model_copy(update={'require_shoes':False,'accessory_pipeline':False,'footwear_pipeline':False})  # Pre-footwear fixtures
    p.evaluate=lambda items:(review(optional=verdict),{})
    lib.build(uid,top.id);run_all(lib)
    result=lib.list(uid,Signer(),'')
    assert result.total==1
    outfit=result.outfits[0]
    assert len(outfit.items)==2
    expected=verdict=='clear_improvement' or (kind=='upper' and verdict=='no_improvement')
    assert bool(outfit.optional_additions)==expected
    if not expected:
        core_ids={i.id for i in outfit.items}
        removed=next(i for i in p.ids if i not in core_ids)
        assert lib.list(uid,Signer(),'',removed).total==0


def test_compatible_outerwear_survives_without_admitting_redundant_accessory(setup):
    from uuid import uuid4
    uid,top,bottom,lib,p=setup
    coat=top.model_copy(update={'id':str(uuid4()),'category':'Outerwear','subtype':'Jacket'})
    hat=top.model_copy(update={'id':str(uuid4()),'category':'Accessories','subtype':'Hat'})
    for item in [coat,hat]:lib.repository.add_item(item)
    p.ids=[top.id,bottom.id,coat.id,hat.id]
    lib.config=load_config().model_copy(update={'require_shoes':False,'accessory_pipeline':False,'footwear_pipeline':False})
    p.evaluate=lambda items:(review(optional='no_improvement'),{})
    lib.build(uid,top.id);run_all(lib)
    outfit=lib.list(uid,Signer(),'').outfits[0]
    assert len(outfit.optional_additions)==1
    assert {i.id for i in outfit.optional_additions[0].items}=={coat.id}
    assert lib.list(uid,Signer(),'',coat.id).total==1
    assert lib.list(uid,Signer(),'',hat.id).total==0
