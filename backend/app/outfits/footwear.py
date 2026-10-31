"""Clothing-first generation, batched accessory selection and visual review."""
from collections import defaultdict
from uuid import NAMESPACE_URL, uuid5

from app.outfits.catalog import rank_score, select_catalog
from app.outfits.compatibility import core_items, compatibility_issues, slot
from app.outfits.config import digest
from app.outfits.diagnostics import OutfitValidationError
from app.outfits.models import BatchAccessorySelections, BatchVisualReviews, VisualReview
from app.outfits.store import now
from app.services.taste_profile import taste_review_key


def shoe_pool_revision(items, include_accessories=False):
    from app.outfits.service import revision
    return digest({i.id: revision(i) for i in items if slot(i) == 'Shoes' or (include_accessories and slot(i) == 'Accessories')})


def clothing_catalog(anchor, items, config, taste_profile=None):
    garments = [i for i in items if slot(i) != 'Shoes']
    if config.accessory_pipeline:
        garments = [i for i in garments if slot(i) != 'Accessories' or i.subtype == 'Tights']
    if slot(anchor) != 'Shoes' and not (config.accessory_pipeline and slot(anchor) == 'Accessories' and anchor.subtype != 'Tights'):
        return select_catalog(anchor, garments, config.model_copy(update={'require_shoes': False}),taste_profile)
    groups = defaultdict(list)
    for item in sorted(garments, key=lambda i: i.id): groups[slot(item)].append(item)
    selected = []
    while len(selected) < config.catalog_limit and any(groups.values()):
        for role in ['Tops', 'Bottoms', 'FullBody', 'Outerwear', 'Accessories']:
            if groups[role] and len(selected) < config.catalog_limit: selected.append(groups[role].pop(0))
    return selected


def footwear_catalog(clothing, items, config, anchor=None):
    """Rank by metadata/vector evidence before sending a small diverse pool to vision."""
    core = core_items(clothing)
    shoes = [i for i in items if slot(i) == 'Shoes' and i.user_id == clothing[0].user_id
             and not compatibility_issues(core + [i], config.compatibility_rules)]
    scores = {shoe.id: sum(rank_score(piece, shoe, config) for piece in core) / max(1, len(core)) for shoe in shoes}
    groups = defaultdict(list)
    for shoe in sorted(shoes, key=lambda shoe: (-scores[shoe.id], shoe.id)):
        groups[shoe.subtype or 'Unknown'].append(shoe)
    limit = config.footwear_catalog_limit
    if config.accessory_pipeline:
        limit = min(limit, getattr(config, 'vision_footwear_limit', limit))
    chosen = []
    while len(chosen) < limit and any(groups.values()):
        for group in groups.values():
            if group and len(chosen) < limit: chosen.append(group.pop(0))
    if anchor is not None and slot(anchor) == 'Shoes' and anchor.id not in {s.id for s in chosen}:
        chosen = chosen[:limit - 1] + [anchor]
    return chosen


def admitted_evidence(payload, pool_revision):
    evidence = payload.get('footwear') or {}
    if evidence.get('shoe_pool_revision') != pool_revision: return False
    if evidence.get('pipeline') in {'accessories_full_review_v1', 'accessories_batched_full_review_v2'}:
        selected = evidence.get('selection', {}).get('selected_shoe_id')
        return bool(selected and selected in payload.get('item_ids', []) and payload.get('visual_review'))
    return False


def _prepared_candidates(anchor, catalog, proposals, config, stats):
    from app.outfits.service import signature, structural_rejection_codes
    allowed, seen, prepared = {i.id: i for i in catalog}, set(), []
    for candidate_index, proposal in enumerate(proposals.outfits, start=1):
        ids, rejection_codes = proposal.item_ids, []
        if not 1 <= len(ids) < config.max_items_per_outfit: rejection_codes.append('invalid_item_count')
        if len(ids) != len(set(ids)): rejection_codes.append('duplicate_item')
        if any(i not in allowed for i in ids): rejection_codes.append('item_outside_candidate_catalog')
        if slot(anchor) != 'Shoes' and not (config.accessory_pipeline and slot(anchor) == 'Accessories') and anchor.id not in ids:
            rejection_codes.append('missing_anchor')
        if rejection_codes:
            stats['invalid'] += 1
            stats['candidate_diagnostics'].append({'candidate_index': candidate_index, 'item_ids': ids,
                'status': 'rejected_before_accessories', 'rejection_codes': rejection_codes})
            continue
        clothing = [allowed[i] for i in ids]
        rejection_codes = structural_rejection_codes(clothing)
        compatibility = compatibility_issues(clothing, config.compatibility_rules)
        if compatibility: rejection_codes.append('compatibility_rule')
        if rejection_codes:
            stats['invalid'] += 1
            diagnostic = {'candidate_index': candidate_index, 'item_ids': ids,
                'status': 'rejected_before_accessories', 'rejection_codes': rejection_codes}
            if compatibility: diagnostic['compatibility_issues'] = compatibility
            stats['candidate_diagnostics'].append(diagnostic); continue
        stats['candidate_diagnostics'].append({'candidate_index': candidate_index, 'item_ids': ids,
            'status': 'passed_clothing_rules', 'rejection_codes': []})
        clothing_signature = signature(clothing)
        if clothing_signature in seen: continue
        seen.add(clothing_signature)
        prepared.append({'candidate_index': candidate_index, 'proposal': proposal, 'ids': ids, 'clothing': clothing})
    return prepared


def _accessories_for(clothing, anchor, items, config):
    ids = {c.id for c in clothing}
    accessories = [i for i in items if slot(i) == 'Accessories' and i.subtype != 'Tights' and i.id not in ids]
    accessories.sort(key=lambda a: (-sum(rank_score(c, a, config) for c in clothing), a.id))
    limit = min(config.accessory_catalog_limit, getattr(config, 'vision_accessory_limit', config.accessory_catalog_limit))
    accessories = accessories[:limit]
    if slot(anchor) == 'Accessories' and anchor.subtype != 'Tights' and anchor.id not in {a.id for a in accessories} and limit:
        accessories = accessories[:limit - 1] + [anchor]
    return accessories


def _process_accessory_batch(library, job, run, anchor, all_items, prepared, pool_revision, generation_call, stats, provider):
    from app.outfits.service import revision, signature, combined_revision, structurally_valid
    config, store, uid = library.config, library.store, job['user_id']
    selectable = []
    for entry in prepared:
        entry['shoes'] = footwear_catalog(entry['clothing'], all_items, config, anchor)
        entry['accessories'] = _accessories_for(entry['clothing'], anchor, all_items, config)
        if not entry['shoes']:
            stats['footwear_rejections'].append({'clothing_ids': entry['ids'], 'shoe_pool_revision': pool_revision,
                'candidate_ids': [], 'reason': 'no_suitable_shoes'})
        else: selectable.append(entry)
    if not selectable:
        store.finish(job, 'complete', stats); return

    batch, _, selection_call = library.checked_call(store, job, run, 'generation', config.footwear_selection_model,
        lambda: provider.select_accessories_batch([(e['candidate_index'], e['clothing'], e['shoes'], e['accessories']) for e in selectable]),
        phase='accessory_selection')
    if not isinstance(batch, BatchAccessorySelections): raise OutfitValidationError('invalid_accessory_selection')
    expected = {e['candidate_index'] for e in selectable}
    selections, duplicate_selections = {}, set()
    for selection in batch.selections:
        if selection.candidate_index in selections:
            duplicate_selections.add(selection.candidate_index)
        elif selection.candidate_index in expected:
            selections[selection.candidate_index] = selection

    cache, pending, accepted = {r['id']: r for r in store.evaluations(uid)}, [], []
    for entry in selectable:
        selection = selections.get(entry['candidate_index'])
        shoes, accessories, clothing = entry['shoes'], entry['accessories'], entry['clothing']
        if selection is None or entry['candidate_index'] in duplicate_selections:
            stats['invalid'] += 1
            stats['candidate_diagnostics'].append({'candidate_index': entry['candidate_index'],
                'item_ids': entry['ids'], 'status': 'rejected_accessory_selection',
                'rejection_codes': ['missing_or_duplicate_batch_result']})
            continue
        if (selection.selected_shoe_id not in {None, *[s.id for s in shoes]}
                or len(selection.accessory_ids) != len(set(selection.accessory_ids))
                or not set(selection.accessory_ids) <= {a.id for a in accessories}
                or len(clothing) + 1 + len(selection.accessory_ids) > config.max_items_per_outfit):
            stats['invalid'] += 1
            stats['candidate_diagnostics'].append({'candidate_index': entry['candidate_index'],
                'item_ids': entry['ids'], 'status': 'rejected_accessory_selection',
                'rejection_codes': ['invalid_candidate_ids_or_item_count']})
            continue
        evidence = {'pipeline': 'accessories_batched_full_review_v2', 'shoe_pool_revision': pool_revision,
            'candidate_ids': [s.id for s in shoes], 'accessory_candidate_ids': [a.id for a in accessories],
            'selection': selection.model_dump(exclude={'candidate_index'}), 'selection_call_id': selection_call}
        reject = {'clothing_ids': entry['ids'], **evidence}
        if selection.selected_shoe_id is None:
            stats['footwear_rejections'].append({**reject, 'reason': 'no_suitable_shoes'}); continue
        if slot(anchor) == 'Shoes' and selection.selected_shoe_id != anchor.id:
            stats['footwear_rejections'].append({**reject, 'reason': 'anchor_shoe_not_best'}); continue
        selected = next(s for s in shoes if s.id == selection.selected_shoe_id)
        members = clothing + [selected] + [a for a in accessories if a.id in selection.accessory_ids]
        if slot(anchor) == 'Accessories' and anchor.id not in {i.id for i in members}: continue
        if not structurally_valid(members, require_shoes=True): stats['invalid'] += 1; continue
        sig = signature(members)
        rev = digest([combined_revision(members), pool_revision, sorted(s.id for s in shoes)])
        record_id = str(uuid5(NAMESPACE_URL, digest([uid, sig, rev, config.evaluator_key,
            taste_review_key(getattr(library, 'taste_profile', None))])))
        data = {**entry, 'evidence': evidence, 'members': members, 'sig': sig, 'rev': rev, 'record_id': record_id}
        saved = cache.get(record_id)
        if saved and admitted_evidence(saved['payload'], pool_revision):
            data.update(evaluation=VisualReview.model_validate(saved['payload']['visual_review']), saved=True)
            stats['cached'] += 1; accepted.append(data)
        else: pending.append(data)

    evaluation_call = None
    if pending:
        reviews, _, evaluation_call = library.checked_call(store, job, run, 'evaluation', config.evaluation_model,
            lambda: provider.evaluate_batch([(e['candidate_index'], e['members']) for e in pending]),
            phase='full_outfit_review')
        if not isinstance(reviews, BatchVisualReviews): raise OutfitValidationError('invalid_full_review')
        expected = {e['candidate_index'] for e in pending}
        by_index, duplicate_reviews = {}, set()
        for result in reviews.reviews:
            if result.candidate_index in by_index:
                duplicate_reviews.add(result.candidate_index)
            elif result.candidate_index in expected:
                by_index[result.candidate_index] = result.review
        latest = library.items(uid)
        member_map = {i.id: i for entry in pending for i in entry['members']}
        if shoe_pool_revision(latest.values(), True) != pool_revision or any(
                i.id not in latest or revision(i) != revision(latest[i.id]) for i in member_map.values()):
            raise OutfitValidationError('garment_snapshot_changed')
        for entry in pending:
            if entry['candidate_index'] not in by_index or entry['candidate_index'] in duplicate_reviews:
                stats['invalid'] += 1
                stats['candidate_diagnostics'].append({'candidate_index': entry['candidate_index'],
                    'item_ids': entry['ids'], 'status': 'rejected_final_review',
                    'rejection_codes': ['missing_or_duplicate_batch_result']})
                continue
            entry.update(evaluation=by_index[entry['candidate_index']], saved=False); accepted.append(entry)

    for entry in accepted:
        evaluation = entry['evaluation']
        if not entry['saved']:
            members = entry['members']
            record = {'id': entry['record_id'], 'user_id': uid, 'signature': entry['sig'], 'revision': entry['rev'],
                'evaluator_key': config.evaluator_key, 'payload': {'item_ids': sorted(i.id for i in members),
                'item_revisions': {i.id: revision(i) for i in members}, 'evaluation': evaluation.diagnostic().model_dump(),
                'visual_review': evaluation.model_dump(), 'footwear': entry['evidence'], 'run_id': run['id'],
                'generation_key': config.generation_key,
                'policy_version': 3, 'generation_reason': entry['proposal'].reason,
                'generation_call_id': generation_call, 'evaluation_call_id': evaluation_call,
                'anchor_item_id': anchor.id, 'evaluated_at': now()}}
            if hasattr(store, 'save_checked'):
                if not store.save_checked(record, job, members):
                    store.finish(job, 'obsolete', stats, 'Lease or garment snapshot changed'); return
            else: store.save(record)
            stats['evaluated'] += 1
        store.link_result(run['id'], entry['record_id'], entry['saved'])
        if library.passes(evaluation): stats['passing'] += 1
    store.finish(job, 'complete', stats)


def process(library, job, run, anchor, items, provider, stats):
    """Generate once, then use at most one accessory call and one final-review call."""
    from app.services.taste_profile import exploration_quota_met, generation_taste_context
    config, store = library.config, library.store
    pool_revision = shoe_pool_revision(items.values(), config.accessory_pipeline)
    if not any(slot(i) == 'Shoes' for i in items.values()):
        store.finish(job, 'complete', stats, 'No recognized shoes available'); return
    catalog = clothing_catalog(anchor, list(items.values()), config, getattr(library,'taste_profile',None))
    proposals, _, generation_call = library.checked_call(store, job, run, 'generation', config.generation_model,
        lambda: provider.generate_clothing(anchor, catalog), phase='clothing_generation')
    if len(proposals.outfits) > config.candidates_per_anchor: raise OutfitValidationError('too_many_proposals')
    stats.update(generated=len(proposals.outfits), footwear_rejections=[], candidate_diagnostics=[])
    prepared = _prepared_candidates(anchor, catalog, proposals, config, stats)
    taste_context = generation_taste_context(anchor, catalog, getattr(library, 'taste_profile', None),
                                             config.candidates_per_anchor)
    if not exploration_quota_met([entry['proposal'] for entry in prepared], taste_context):
        raise OutfitValidationError('taste_exploration_quota_not_met')
    return _process_accessory_batch(library, job, run, anchor, list(items.values()), prepared,
                                    pool_revision, generation_call, stats, provider)
