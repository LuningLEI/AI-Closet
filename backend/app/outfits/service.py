from __future__ import annotations
from collections import Counter
from app.outfits.diagnostics import error_details
from uuid import uuid5, NAMESPACE_URL
from app.outfits.config import digest, OutfitConfig
from app.outfits.models import Evaluation, VisualReview, LibraryResponse, OutfitDTO, OutfitVariantDTO
from app.services.layering_support import valid_layering
from app.outfits.compatibility import core_items, accessory_role, compatibility_issues, slot
from app.outfits.provider import VisionOutfitProvider
from app.outfits.runs import run_manifest, tracked_call
from app.outfits.store import now
from app.services.recommendation.rules import recommendation_slot, layers_compatible, tights_layering_valid
from app.services.taste_profile_service import TasteProfileService
from app.services.personalization_settings import exploration_rate, resolve_personalization_settings
from app.services.taste_profile import exploration_quota_met, generation_taste_context, taste_review_key
from app.services.layering_fit import assess_outfit_layering

ATTRIBUTES = ('image_path','category','subtype','color','style','material','pattern','fit','length',
              'sleeve_length','neckline','layering_role')
LEGACY_ATTRIBUTES = ATTRIBUTES
ATTRIBUTES = ATTRIBUTES + ('occasion', 'season', 'warmth_level', 'formality_score', 'wearing_profile', 'color_tones')
SUPPORTED = {'Tops','Bottoms','FullBody','Outerwear','Shoes','Accessories'}
MANUAL_ONLY_ANCHOR_CATEGORIES = frozenset({'Bags', 'Shoes', 'Accessories'})

def revision(item):
    # Exclude occasion/weather thresholds, mutable signed URLs and timestamps.
    return digest({k:getattr(item,k) for k in ATTRIBUTES})

def record_revision_matches(payload, item):
    stored = payload['item_revisions'].get(item.id)
    if stored == revision(item):return True
    # Old results remain reviewable under the new explicit compatibility rules.
    return payload.get('policy_version', 1) < 2 and stored == digest({k:getattr(item,k) for k in LEGACY_ATTRIBUTES})


def ready(item):
    return item.recognition_status in {'complete','manual'} and recommendation_slot(item.category, item.subtype) in SUPPORTED

def automatic_anchor(item):
    """Keep add-ons in candidate pools without spending one automatic job per add-on."""
    return item.category not in MANUAL_ONLY_ANCHOR_CATEGORIES

def signature(items):return digest(sorted(i.id for i in items))
def combined_revision(items):return digest({i.id:revision(i) for i in items})

def structural_rejection_codes(items, require_shoes=False):
    codes=[]
    if not tights_layering_valid(items):codes.append('invalid_tights_layering')
    if not valid_layering(items):codes.append('invalid_layering_direction_or_coverage')
    roles=Counter(recommendation_slot(i.category, i.subtype) for i in items)
    if len({i.id for i in items})!=len(items):codes.append('duplicate_item')
    if any(r not in SUPPORTED for r in roles):codes.append('unsupported_category_slot')
    if roles['FullBody']>1:codes.append('multiple_full_body_items')
    if roles['Outerwear']>1:codes.append('multiple_outerwear_items')
    if roles['Shoes']>1:codes.append('multiple_shoes')
    if require_shoes and roles['Shoes'] != 1:codes.append('missing_required_shoes')
    accessories=[accessory_role(i) for i in items if slot(i)=='Accessories']
    if len(accessories)!=len(set(accessories)):codes.append('duplicate_accessory_role')
    if roles['FullBody']:
        if roles['Tops']:codes.append('full_body_with_top')
        if roles['Bottoms']>1:codes.append('full_body_with_multiple_bottoms')
        return codes
    tops=[i for i in items if recommendation_slot(i.category, i.subtype)=='Tops']
    from app.services.outerwear_policy import outerwear_can_replace_top
    standalone_outerwear=[i for i in items if recommendation_slot(i.category,i.subtype)=='Outerwear'
        and outerwear_can_replace_top(i)]
    if roles['Bottoms']<1:codes.append('missing_bottom')
    if roles['Bottoms']>2:codes.append('too_many_bottom_layers')
    if not tops and not standalone_outerwear:codes.append('missing_top')
    elif len(tops)>2:codes.append('too_many_top_layers')
    elif len(tops)==2 and not (layers_compatible(tops[0],tops[1]) or layers_compatible(tops[1],tops[0])):
        codes.append('incompatible_top_layers')
    return codes


def structurally_valid(items, require_shoes=False):
    return not structural_rejection_codes(items, require_shoes=require_shoes)

class SupersededOutfitJob(Exception):
    """The anchor changed before a paid model call."""


class OutfitLibrary:
    def __init__(self, repository, store, config, provider=None):
        self.repository,self.store,self.config=repository,store,config
        self.provider=provider

    def items(self, uid, include_vectors=False):
        read = getattr(self.repository, 'list_items_for_outfit_candidates', self.repository.list_items_for_outfits) if include_vectors else self.repository.list_items_for_outfits
        return {i.id:i for i in read(uid) if i.user_id==uid and ready(i)}

    def job_data(self, uid, item):
        rev=revision(item)
        identity=[uid,item.id,rev,self.config.generation_key]
        return {'id':digest(identity),'user_id':uid,
                'anchor_item_id':item.id,'revision':rev,'generation_key':self.config.generation_key}

    @staticmethod
    def _logical_job_key(job):
        """Deduplicate old pool-scoped jobs against the new anchor-scoped identity."""
        return (job['anchor_item_id'], job['revision'], job['generation_key'])

    def sync(self, uid, anchor_id=None):
        items=self.items(uid)
        if anchor_id is not None and anchor_id not in items:raise ValueError('This item is not ready for outfit generation')
        existing={self._logical_job_key(job) for job in self.store.jobs(uid)}
        # A focused request is an explicit user action and may use any ready item.
        # Full-library/reconciliation scans skip add-ons as anchors, while `items`
        # remains unchanged so those add-ons are still available to clothing jobs.
        anchors=(items.values() if anchor_id is None else [items[anchor_id]])
        if anchor_id is None:
            anchors=(item for item in anchors if automatic_anchor(item))
        jobs=[self.job_data(uid,item) for item in anchors]
        jobs=[job for job in jobs if self._logical_job_key(job) not in existing]
        if not jobs:return 0
        return self.store.enqueue_run(run_manifest(uid,jobs,self.config),jobs)

    def build(self, uid, anchor_id=None, retry_failed=False):
        count=self.sync(uid,anchor_id)
        if anchor_id is None:
            self.store.enroll(uid)
        if retry_failed:self.store.retry(uid)
        return {'queued':count,'jobs':self.progress(uid)}

    def progress(self, uid, items=None):
        items=self.items(uid) if items is None else items
        keys={self._logical_job_key(self.job_data(uid,item)) for item in items.values()}
        # Pool-scoped historical jobs can share one logical anchor revision.
        # Count that anchor once and prefer its completed result over a later
        # obsolete duplicate, otherwise the UI incorrectly reports the whole
        # wardrobe as still remaining after this migration.
        priority={'complete':5,'processing':4,'queued':3,'failed':2,'obsolete':1}
        logical={}
        for job in self.store.jobs(uid):
            key=self._logical_job_key(job)
            if key not in keys:continue
            if key not in logical or priority.get(job['status'],0)>priority.get(logical[key],0):
                logical[key]=job['status']
        return dict(Counter(logical.values()))

    def select_catalog(self, anchor, items):
        from app.outfits.catalog import select_catalog
        return select_catalog(anchor, items, self.config, getattr(self,'taste_profile',None))

    def checked_call(self, store, job, run, stage, model, invoke, phase=None):
        # Re-read before EVERY paid stage, not just when the job was claimed.
        items = self.items(job['user_id'])
        anchor = items.get(job['anchor_item_id'])
        if (anchor is None or revision(anchor) != job['revision']
                or job['generation_key'] != self.config.generation_key):
            raise SupersededOutfitJob()
        return tracked_call(store, job, run, stage, model, invoke, phase=phase)

    def process(self, job):
        original_config=self.config
        stats={'generated':0,'invalid':0,'evaluated':0,'cached':0,'passing':0}
        try:
            uid=job['user_id'];items=self.items(uid, include_vectors=True);anchor=items.get(job['anchor_item_id'])
            preference_record=self.repository.get_preferences(uid)
            settings=resolve_personalization_settings(preference_record.get('preferences'))
            if settings.personalization_enabled and settings.feedback_learning_enabled:
                self.taste_profile=TasteProfileService(self.store).ensure_current(uid)
                memory=dict(self.taste_profile.get('generation_memory') or {})
                memory['exploration_rate']=exploration_rate(settings)
                self.taste_profile={**self.taste_profile,'generation_memory':memory}
            else:
                self.taste_profile={}
            stats['taste_profile_version']=self.taste_profile.get('profile_version',0)
            if not anchor or revision(anchor)!=job['revision'] or job['generation_key']!=self.config.generation_key:
                self.store.finish(job,'obsolete',stats);return
            run=self.store.ensure_job_run(job,run_manifest(uid,[job],self.config))
            # Runtime provenance travels beside the executable outfit config.
            # It is intentionally excluded from the strict policy model.
            executable_config = dict(run['config'])
            executable_config.pop('runtime_snapshot', None)
            self.config=OutfitConfig.model_validate(executable_config)
            provider=self.provider or VisionOutfitProvider(self.config)
            provider.taste_profile=self.taste_profile
            if not self.config.footwear_pipeline:
                self._process_visual_only(job, run, anchor, items, provider, stats)
                return
            from app.outfits.footwear import process
            process(self,job,run,anchor,items,provider,stats)
            return
        except SupersededOutfitJob:
            self.store.finish(job, 'obsolete', stats, 'Garment version changed before model call')
            # Queue the current version immediately; sync deduplicates job IDs.
            self.sync(job['user_id'])
        except Exception as error:
            # Avoid persisting provider payloads or signed image URLs in job errors.
            status='failed' if job['attempts']>=self.config.max_attempts else 'queued'
            stats['error_diagnostics'] = error_details(error)
            self.store.finish(job,status,stats,f'{type(error).__name__}: outfit generation/evaluation failed; see stats.error_diagnostics')
            raise
        finally:
            self.taste_profile=None
            self.config=original_config

    def _process_visual_only(self, job, run, anchor, items, provider, stats):
        """Compatibility path for archived runs; production config cannot select it."""
        uid = job['user_id']
        catalog = self.select_catalog(anchor, list(items.values()))
        allowed = {item.id: item for item in catalog}
        proposals, _, generation_call_id = self.checked_call(
            self.store, job, run, 'generation', self.config.generation_model,
            lambda: provider.generate(anchor, catalog))
        if len(proposals.outfits) > self.config.candidates_per_anchor:
            raise ValueError('Generator exceeded configured candidate count')
        taste_context = generation_taste_context(
            anchor, catalog, self.taste_profile, self.config.candidates_per_anchor)
        valid = []
        for proposal in proposals.outfits:
            ids = proposal.item_ids
            if (anchor.id in ids and len(ids) == len(set(ids))
                    and 1 <= len(ids) <= self.config.max_items_per_outfit
                    and all(item_id in allowed for item_id in ids)):
                members = [allowed[item_id] for item_id in ids]
                layering = assess_outfit_layering(members, self.config.layering_fit_policy)
                if (not structural_rejection_codes(members, require_shoes=self.config.require_shoes)
                        and not compatibility_issues(members, self.config.compatibility_rules)
                        and not (layering and layering.hard_failure)):
                    valid.append(proposal)
        # Keep exploration as a long-horizon ranking/exposure target.  It must not
        # invalidate an otherwise usable paid batch merely because structural
        # filtering changed the exact per-batch count.
        stats['exploration_quota_met'] = exploration_quota_met(valid, taste_context)
        if not stats['exploration_quota_met']:
            stats['exploration_quota_warning'] = 'batch_quota_missed_after_structural_filtering'
        stats['generated'] = len(proposals.outfits)
        stats['candidate_diagnostics'] = []
        cache = {record['id']: record for record in self.store.evaluations(uid)}
        seen = set()
        for candidate_index, proposal in enumerate(proposals.outfits, start=1):
            ids = proposal.item_ids
            rejection_codes = []
            if anchor.id not in ids: rejection_codes.append('missing_anchor')
            if len(ids) != len(set(ids)): rejection_codes.append('duplicate_item')
            if not 1 <= len(ids) <= self.config.max_items_per_outfit: rejection_codes.append('invalid_item_count')
            if any(item_id not in allowed for item_id in ids): rejection_codes.append('item_outside_candidate_catalog')
            if rejection_codes:
                stats['invalid'] += 1
                stats['candidate_diagnostics'].append({'candidate_index': candidate_index, 'item_ids': ids,
                    'status': 'rejected_before_visual_review', 'rejection_codes': rejection_codes})
                continue
            members = [allowed[item_id] for item_id in ids]
            rejection_codes = structural_rejection_codes(members, require_shoes=self.config.require_shoes)
            compatibility = compatibility_issues(members, self.config.compatibility_rules)
            if compatibility: rejection_codes.append('compatibility_rule')
            layering = assess_outfit_layering(members, self.config.layering_fit_policy)
            if layering and layering.hard_failure: rejection_codes.append('physical_layering_capacity_conflict')
            if rejection_codes:
                stats['invalid'] += 1
                stats['candidate_diagnostics'].append({'candidate_index': candidate_index, 'item_ids': ids,
                    'status': 'rejected_before_visual_review', 'rejection_codes': rejection_codes,
                    'compatibility_issues': compatibility,
                    'layering_reasons': list(layering.reasons) if layering and layering.hard_failure else []})
                continue
            sig = signature(members)
            rev = combined_revision(members)
            record_id = str(uuid5(NAMESPACE_URL, digest([
                uid, sig, rev, self.config.evaluator_key, taste_review_key(self.taste_profile)])))
            if record_id in seen: continue
            seen.add(record_id)
            saved = cache.get(record_id)
            if saved:
                evaluation = VisualReview.model_validate(saved['payload']['visual_review'])
                stats['cached'] += 1
            else:
                evaluation, _, evaluation_call_id = self.checked_call(
                    self.store, job, run, 'evaluation', self.config.evaluation_model,
                    lambda: provider.evaluate(members))
                if not isinstance(evaluation, VisualReview):
                    raise ValueError('Visual review required')
                latest = self.items(uid)
                if any(item.id not in latest or revision(item) != revision(latest[item.id]) for item in members):
                    self.store.finish(job, 'queued' if job['attempts'] < self.config.max_attempts else 'failed',
                                      stats, 'Closet changed during evaluation; retry required')
                    return
                record = {'id': record_id, 'user_id': uid, 'signature': sig, 'revision': rev,
                    'evaluator_key': self.config.evaluator_key, 'payload': {
                        'item_ids': sorted(ids), 'item_revisions': {item.id: revision(item) for item in members},
                        'evaluation': evaluation.diagnostic().model_dump(), 'visual_review': evaluation.model_dump(),
                        'generation_key': self.config.generation_key, 'run_id': run['id'], 'policy_version': 2,
                        'taste_profile_version': self.taste_profile.get('profile_version', 0),
                        'generation_reason': proposal.reason, 'generation_call_id': generation_call_id,
                        'evaluation_call_id': evaluation_call_id, 'anchor_item_id': anchor.id,
                        'evaluated_at': now()}}
                if hasattr(self.store, 'save_checked'):
                    if not self.store.save_checked(record, job, members):
                        raise ValueError('Lease or garment snapshot changed')
                else:
                    self.store.save(record)
                stats['evaluated'] += 1
            self.store.link_result(run['id'], record_id, bool(saved))
            if self.passes(evaluation): stats['passing'] += 1
        self.store.finish(job, 'complete', stats)

    def passes(self, evaluation):
        return isinstance(evaluation,VisualReview) and evaluation.core.passes()

    @property
    def projection_key(self):
        return digest(['current-outfits-v5-outerwear-standalone-policy',self.config.require_shoes,self.config.evaluator_key,
                       self.config.compatibility_rules.model_dump()])

    def refresh_projection(self, uid):
        if not hasattr(self.store,'projection_state'):return
        state=self.store.projection_state(uid)
        if state['source_version']==state['projected_version'] and state['projection_key']==self.projection_key:return
        class IdentitySigner:
            def items(self,items,base_url):return items
        provenance={}
        result=self._records_list(uid,IdentitySigner(),'',limit=10_000_000,provenance=provenance)
        # A concurrent mutation rejects the publication; the durable dirty version
        # remains pending and is picked up in the next worker reconciliation.
        return self.store.publish_projection(uid,state['source_version'],self.projection_key,
            [{**outfit.model_dump(mode='json'),'source_evaluation_ids':sorted(provenance[outfit.id])} for outfit in result.outfits])

    def list(self, uid, signer, base_url, anchor_id=None, offset=0, limit=30):
        if not hasattr(self.store,'projected_page'):
            from app.outfits.personal import PersonalOutfits
            personal=PersonalOutfits(self.repository,self.store).list(uid,anchor_id)
            result=self._records_list(uid,signer,base_url,anchor_id,0,10_000_000)
            signatures={tuple(sorted(i.id for i in o.items)) for o in personal}
            for o in personal:o.items=signer.items(o.items,base_url)
            combined=sorted(personal+[o for o in result.outfits if tuple(sorted(i.id for i in o.items)) not in signatures],key=lambda o:o.id)
            result.total=len(combined);result.outfits=combined[offset:offset+limit]
            result.next_offset=offset+limit if offset+limit<len(combined) else None
            return result
        result=LibraryResponse.model_validate(self.store.projected_page(uid,self.projection_key,self.config.generation_key,anchor_id,offset,limit))
        # Only sign images on the requested page. Never scan evaluation history here.
        unique={}
        for outfit in result.outfits:
            for item in outfit.items+[i for v in outfit.optional_additions for i in v.items]:unique[item.id]=item
        signed={i.id:i for i in signer.items(list(unique.values()),base_url)} if unique else {}
        for outfit in result.outfits:
            outfit.items=[signed[i.id] for i in outfit.items]
            for variant in outfit.optional_additions:variant.items=[signed[i.id] for i in variant.items]
        return result

    def _records_list(self, uid, signer, base_url, anchor_id=None, offset=0, limit=30, provenance=None):
        items=self.items(uid);groups={}
        display_order={'FullBody':0,'Tops':0,'Bottoms':1,'Outerwear':2,'Shoes':3,'Accessories':4}
        order=lambda i:(display_order[slot(i)],i.id)
        rows=self.store.evaluations(uid)
        from app.outfits.footwear import admitted_evidence
        valid=[]
        for row in rows:
            payload=row['payload'];ids=payload['item_ids']
            if row['evaluator_key']!=self.config.evaluator_key:continue
            if self.config.footwear_pipeline and not admitted_evidence(payload):continue
            if any(i not in items or not record_revision_matches(payload,items[i]) for i in ids):continue
            valid.append(row)
        # A new rejection must override an old accepted variant. Keep unreviewed
        # historical combinations visible as pending, not falsely vision-approved.
        reviewed={}
        core_reviews={}
        core_review_ids={}
        for row in sorted(valid,key=lambda r:r['payload'].get('evaluated_at','')):
            if row['evaluator_key']==self.config.evaluator_key and row['payload'].get('visual_review'):
                reviewed[row['signature']]=row
                members=[items[i] for i in row['payload']['item_ids']]
                core_reviews[signature(core_items(members, require_shoes=self.config.require_shoes))]=VisualReview.model_validate(row['payload']['visual_review'])
                core_review_ids[signature(core_items(members, require_shoes=self.config.require_shoes))]=row['id']
        for row in valid:
            payload=row['payload'];ids=payload['item_ids']
            if row['evaluator_key']!=self.config.evaluator_key:continue
            if self.config.footwear_pipeline and not admitted_evidence(payload):continue
            if row['signature'] in reviewed and reviewed[row['signature']]['id']!=row['id']:continue
            members=sorted([items[i] for i in ids],key=order)
            core=core_items(members, require_shoes=self.config.require_shoes)
            core_layering = assess_outfit_layering(core, self.config.layering_fit_policy)
            if (not structurally_valid(core, require_shoes=self.config.require_shoes)
                    or compatibility_issues(core, self.config.compatibility_rules)
                    or (core_layering and core_layering.hard_failure)):
                continue
            sig=signature(core)
            review=core_reviews.get(sig)
            if review and not review.core.passes():continue
            status='passed' if review else 'pending'
            evaluation=review.diagnostic() if review else Evaluation.model_validate(payload['evaluation'])
            group=groups.setdefault(sig,{'core':core,'evaluation':evaluation,'variants':{},'variant_status':{},'status':status,'sources':set()})
            group['sources'].add(row['id'])
            if sig in core_review_ids:group['sources'].add(core_review_ids[sig])
            # A bad optional coat must not remove a valid top+bottom combination.
            extras=[i for i in members if i not in core]
            full_review=VisualReview.model_validate(payload['visual_review']) if row['evaluator_key']==self.config.evaluator_key and payload.get('visual_review') else None
            approved_extras=extras
            optional_decisions = {
                value.get('item_id'): value for value in payload.get('optional_item_reviews', [])
                if isinstance(value, dict) and value.get('item_id')
            }
            if full_review is not None and optional_decisions:
                approved_extras = [
                    item for item in extras
                    if optional_decisions.get(item.id, {}).get('verdict') == 'clear_improvement'
                    or (slot(item) == 'Outerwear'
                        and optional_decisions.get(item.id, {}).get('verdict') == 'no_improvement')
                ]
            elif full_review is not None and full_review.optional_layering.verdict!='clear_improvement':
                # Compatible outerwear can remain a useful colder-weather option
                # without claiming that it aesthetically improves the base. Other
                # removable layers/accessories retain the clear-improvement bar.
                approved_extras=[i for i in extras if slot(i)=='Outerwear'] \
                    if full_review.optional_layering.verdict=='no_improvement' else []
            full_members = core + approved_extras
            full_layering = assess_outfit_layering(full_members, self.config.layering_fit_policy)
            if (approved_extras and (full_review is None or full_review.full.passes())
                    and structurally_valid(full_members, require_shoes=self.config.require_shoes)
                    and not compatibility_issues(full_members, self.config.compatibility_rules)
                    and not (full_layering and full_layering.hard_failure)):
                group['variants'][signature(approved_extras)]=approved_extras
                group['variant_status'][signature(approved_extras)]='passed' if full_review else 'pending'
        if anchor_id:
            filtered={}
            for sig,group in groups.items():
                if anchor_id in {i.id for i in group['core']}:
                    filtered[sig]=group
                else:
                    matching={key:value for key,value in group['variants'].items() if any(i.id==anchor_id for i in value)}
                    if matching:filtered[sig]={**group,'variants':matching}
            groups=filtered
        ranked=sorted(groups.items())
        page=ranked[offset:offset+limit]
        unique={i.id:i for _,g in page for i in g['core']+[i for values in g['variants'].values() for i in values]}
        signed={i.id:i for i in signer.items(list(unique.values()),base_url)} if page else {}
        result=[]
        for sig,g in page:
            if provenance is not None:provenance[str(uuid5(NAMESPACE_URL,digest([uid,'core-outfit',sig])))]=g['sources']
            evaluation=g['evaluation']
            variants=[OutfitVariantDTO(id=key,items=[signed[i.id] for i in extras],visual_review_status=g['variant_status'][key]) for key,extras in sorted(g['variants'].items())]
            result.append(OutfitDTO(id=str(uuid5(NAMESPACE_URL,digest([uid,'core-outfit',sig]))),
                items=[signed[i.id] for i in g['core']],optional_additions=variants,
                aesthetic_score=evaluation.aesthetic_score,structural_reason=evaluation.structural_reason,
                aesthetic_reason=evaluation.aesthetic_reason,visual_review_status=g['status']))
        return LibraryResponse(outfits=result,total=len(ranked),jobs=self.progress(uid,items),enrolled=self.store.enrolled(uid),
            next_offset=offset+limit if offset+limit<len(ranked) else None)
