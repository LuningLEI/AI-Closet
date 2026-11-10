from outfit_pipeline_fixture import pipeline
from test_outfit_library import setup
from uuid import uuid4


def test_old_queued_revision_makes_no_model_calls(pipeline):
    uid, top, bottom, shoe, other, lib, provider = pipeline
    lib.build(uid, top.id)
    job = lib.store.claim(lib.config)
    lib.repository.update_item(top.id, {'color': 'Blue'}, uid)
    lib.process(job)
    assert provider.calls == []
    assert next(j for j in lib.store.jobs(uid) if j['id'] == job['id'])['status'] == 'obsolete'
    lib.sync(uid)
    lib.sync(uid)
    current = lib.repository.get_item(top.id, uid)
    latest = lib.job_data(uid, current)['id']
    assert len([j for j in lib.store.jobs(uid) if j['id'] == latest]) == 1


def test_edit_during_generation_stops_remaining_paid_stages(pipeline):
    uid, top, bottom, shoe, other, lib, provider = pipeline
    original = provider.generate_clothing
    def edit_while_generating(anchor, catalog):
        result = original(anchor, catalog)
        lib.repository.update_item(top.id, {'color': 'Blue'}, uid)
        return result
    provider.generate_clothing = edit_while_generating
    lib.build(uid, top.id)
    job = lib.store.claim(lib.config)
    lib.process(job)
    assert provider.calls == ['clothing']
    assert next(j for j in lib.store.jobs(uid) if j['id'] == job['id'])['status'] == 'obsolete'
    current = lib.repository.get_item(top.id, uid)
    latest = lib.job_data(uid, current)['id']
    assert next(j for j in lib.store.jobs(uid) if j['id'] == latest)['status'] == 'queued'
    assert lib.store.evaluations(uid) == []


def test_shoe_or_accessory_pool_changes_do_not_enqueue_whole_closet(pipeline):
    uid, top, bottom, shoe, other, lib, provider = pipeline
    assert lib.build(uid)['queued'] == 2
    original_top_job = lib.job_data(uid, top)['id']

    accessory = top.model_copy(update={
        'id': str(uuid4()), 'category': 'Accessories', 'subtype': 'Scarf',
        'image_path': 'scarf.jpg',
    })
    lib.repository.add_item(accessory)
    assert lib.sync(uid) == 0
    assert lib.job_data(uid, top)['id'] == original_top_job

    lib.repository.update_item(shoe.id, {'color': 'Blue'}, uid)
    lib.repository.update_item(accessory.id, {'color': 'Green'}, uid)
    assert lib.sync(uid) == 0
    assert lib.job_data(uid, top)['id'] == original_top_job

    lib.repository.update_item(top.id, {'color': 'Blue'}, uid)
    assert lib.sync(uid) == 1
    new_jobs = [job for job in lib.store.jobs(uid) if job['anchor_item_id'] == top.id]
    assert len(new_jobs) == 2
    assert new_jobs[-1]['revision'] != new_jobs[0]['revision']


def test_legacy_pool_scoped_job_deduplicates_by_anchor_revision(pipeline):
    uid, top, bottom, shoe, other, lib, provider = pipeline
    current = lib.job_data(uid, top)
    legacy = {**current, 'id': f"{current['id']}-legacy-pool"}
    lib.store.enqueue(legacy)

    assert lib.sync(uid, top.id) == 0
    assert lib.progress(uid)['queued'] == 1


def test_progress_counts_duplicate_pool_jobs_once_and_prefers_complete(pipeline):
    uid, top, bottom, shoe, other, lib, provider = pipeline
    current = lib.job_data(uid, top)
    lib.store.enqueue({**current, 'id': f"{current['id']}-first"})
    first = lib.store.claim(lib.config)
    lib.store.finish(first, 'complete')
    lib.store.enqueue({**current, 'id': f"{current['id']}-pool-change"})
    duplicate = lib.store.claim(lib.config)
    lib.store.finish(duplicate, 'obsolete')

    assert lib.progress(uid) == {'complete': 1}
