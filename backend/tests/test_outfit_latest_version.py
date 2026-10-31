from outfit_pipeline_fixture import pipeline
from test_outfit_library import setup


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
