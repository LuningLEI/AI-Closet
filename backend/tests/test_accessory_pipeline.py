from uuid import uuid4
import pytest
from app.outfits.models import (BatchAccessorySelection,
    BatchAccessorySelections, BatchVisualReview, BatchVisualReviews, CurrentVisualReview)
from outfit_pipeline_fixture import pipeline
from test_outfit_library import setup, run_all, Signer
from test_outfit_visual_review import review


def current_review(**kwargs):
    return CurrentVisualReview.model_validate(review(**kwargs).model_dump())


def configure(pipeline, optional='clear_improvement', none=False):
    uid,top,bottom,shoe,other,lib,p=pipeline
    lib.config=lib.config.model_copy(update={'accessory_pipeline':True})
    hat=top.model_copy(update={'id':str(uuid4()),'category':'Accessories','subtype':'Hat'})
    lib.repository.add_item(hat)
    def select(candidates):
        p.calls.append('accessories_batch')
        selections=[]
        for candidate_index,clothing,shoes,accessories in candidates:
            assert hat.id in {a.id for a in accessories}
            selections.append(BatchAccessorySelection(candidate_index=candidate_index,
                selected_shoe_id=None if none else shoe.id,
                accessory_ids=[] if none else [hat.id],reason='Visible improvement'))
        return BatchAccessorySelections(selections=selections),{}
    def evaluate(candidates):
        p.calls.append('full_review_batch')
        return BatchVisualReviews(reviews=[BatchVisualReview(candidate_index=index,
            review=current_review(optional=optional)) for index,items in candidates
            if hat.id in {i.id for i in items}]),{}
    p.select_accessories_batch=select;p.evaluate_batch=evaluate
    return uid,top,shoe,hat,lib,p


def test_three_calls_with_optional_accessory_and_no_shoe_review(pipeline):
    uid,top,shoe,hat,lib,p=configure(pipeline)
    lib.build(uid,top.id);run_all(lib)
    assert p.calls==['clothing','accessories_batch','full_review_batch']
    result=lib.list(uid,Signer(),'')
    assert result.total==1
    outfit=result.outfits[0]
    assert shoe.id in {i.id for i in outfit.items}
    assert hat.id not in {i.id for i in outfit.items}
    assert any(hat.id in {i.id for i in variant.items} for variant in outfit.optional_additions)
    assert lib.store.run_report(uid)[0]['call_count']==3


def test_unhelpful_accessory_does_not_hide_good_core(pipeline):
    uid,top,shoe,hat,lib,p=configure(pipeline,optional='no_improvement')
    lib.build(uid,top.id);run_all(lib)
    result=lib.list(uid,Signer(),'')
    assert result.total==1
    assert not result.outfits[0].optional_additions


def test_no_suitable_shoes_skips_final_call(pipeline):
    uid,top,shoe,hat,lib,p=configure(pipeline,none=True)
    lib.build(uid,top.id);run_all(lib)
    assert p.calls==['clothing','accessories_batch']
    assert lib.list(uid,Signer(),'').total==0


def test_foreign_accessory_rejected_before_review(pipeline):
    uid,top,shoe,hat,lib,p=configure(pipeline)
    p.select_accessories_batch=lambda candidates:(BatchAccessorySelections(selections=[
        BatchAccessorySelection(candidate_index=candidates[0][0],selected_shoe_id=shoe.id,
            accessory_ids=['foreign'],reason='bad')]),{})
    lib.build(uid,top.id);run_all(lib)
    assert 'full_review_batch' not in p.calls
    assert lib.store.jobs(uid)[0]['stats']['invalid']==1


def test_bad_shoe_in_final_review_rejects_entire_core(pipeline):
    uid,top,shoe,hat,lib,p=configure(pipeline)
    p.evaluate_batch=lambda candidates:(BatchVisualReviews(reviews=[BatchVisualReview(
        candidate_index=index,review=current_review(core='fail')) for index,items in candidates]),{})
    lib.build(uid,top.id);run_all(lib)
    assert lib.list(uid,Signer(),'').total==0


def test_batch_selector_and_review_deduplicate_shared_images(pipeline):
    import json
    from app.outfits.provider import VisionOutfitProvider
    from app.outfits.models import BatchAccessorySelections, BatchVisualReviews
    uid,top,shoe,hat,lib,p=configure(pipeline)
    bottom=p.bottom
    class Storage:
        def signed_image_url(self,*a,**kw):return 'https://example.test/photo'
    provider=VisionOutfitProvider(lib.config,Storage())
    captured=[]
    provider.request=lambda model,prompt,content,schema:captured.append((content,schema))
    provider.select_accessories_batch([(1,[top],[shoe],[hat]),(2,[top,bottom],[shoe],[hat])])
    content,schema=captured[-1]
    assert schema is BatchAccessorySelections
    assert sum(part['type']=='input_image' for part in content)==4
    assert [c['candidate_index'] for c in json.loads(content[0]['text'])['candidates']]==[1,2]
    provider.evaluate_batch([(1,[top,shoe]),(2,[top,bottom,shoe])])
    content,schema=captured[-1]
    assert schema is BatchVisualReviews
    assert sum(part['type']=='input_image' for part in content)==3


def test_two_unique_candidates_still_make_only_three_model_calls(pipeline):
    from app.outfits.models import Proposal, Proposals
    uid,top,shoe,hat,lib,p=configure(pipeline)
    second=p.bottom.model_copy(update={'id':str(uuid4()),'subtype':'Skirt'})
    lib.repository.add_item(second)
    p.generate_clothing=lambda anchor,catalog:(p.calls.append('clothing') or Proposals(outfits=[
        Proposal(item_ids=[top.id,p.bottom.id],reason='one'),
        Proposal(item_ids=[top.id,second.id],reason='two')]),{})
    lib.build(uid,top.id);run_all(lib)
    assert p.calls==['clothing','accessories_batch','full_review_batch']
    assert lib.store.run_report(uid)[0]['call_count']==3
