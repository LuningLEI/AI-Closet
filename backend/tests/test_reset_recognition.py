import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.domain import ClothingAnalysis, ClothingItemRecord, RecognitionJobRecord, RecognitionRecord
from tools.admin.reset_recognition import reset_user_recognition, main
from app.services.recognition_pipeline import RecognitionPipeline
from app.repositories.supabase_closet_repository import SupabaseClosetRepository


def add_item(repository, item_id='one', user_id='owner', **kwargs):
    return repository.add_item(ClothingItemRecord(
        id=item_id, user_id=user_id, category='Dresses', image_url='https://example.test/old-signed.jpg',
        image_path=f'{user_id}/{item_id}.jpg', material='Silk', occasion='Party',
        recognition_tags={'occasion_scores': [{'occasion': 'Party', 'score': 0.9}]},
        feature_vector=[1.0]*13, semantic_vector=[0.5], **kwargs,
    ))


def add_job(repository, item, status='complete'):
    return repository.create_recognition_job(RecognitionJobRecord(
        user_id=item.user_id, clothing_item_id=item.id, filename='original-dress.jpg',
        image_url=item.image_url, image_path=item.image_path, status=status, attempts=3,
    ))


def test_reset_reuses_image_scopes_user_preserves_history_and_worker_completes(repository, tmp_path):
    item = add_item(repository)
    other = add_item(repository, 'two', 'other')
    add_job(repository, item)
    other_job = add_job(repository, other)
    repository.add_recognition_record(RecognitionRecord(
        user_id='owner', clothing_item_id=item.id, provider='old-model', normalized_payload={'occasion':'Party'},
    ))
    report = reset_user_recognition(repository, 'owner', backup_dir=tmp_path/'backups')
    updated = repository.get_item(item.id, 'owner')
    assert updated.image_path == item.image_path and updated.image_url == item.image_url
    assert updated.created_at == item.created_at
    assert updated.category == 'Uncategorized' and updated.material is None
    assert updated.recognition_tags is None and updated.semantic_vector is None and updated.feature_vector is None
    assert updated.recognition_status == 'queued'
    assert repository.get_item(other.id, 'other') == other
    assert repository.list_recognition_jobs('other') == [other_job]
    jobs = repository.list_recognition_jobs('owner')
    assert len(jobs) == 1 and jobs[0].attempts == 0 and jobs[0].status == 'queued'
    assert jobs[0].filename == 'original-dress.jpg' and jobs[0].image_path == item.image_path
    backup = json.loads(Path(report['backup']).read_text())
    assert backup['items'][0]['semantic_vector'] == [0.5]
    assert len(json.loads(repository.recognition_records_path.read_text())) == 1

    class StoredImage:
        def signed_image_url(self, path, **kwargs):
            assert path == item.image_path
            return 'https://example.test/fresh-signed.jpg'

    class Recognizer:
        def analyze(self, filename, image_url, **kwargs):
            assert image_url.endswith('fresh-signed.jpg')
            return ClothingAnalysis(category='Tops', occasion='Work', source='OpenAI Vision')

    class Embeddings:
        def create_embedding(self, text):
            return [0.1]

    # Use the real worker pipeline after resetting, without contacting a provider.
    job = next(j for j in repository.claim_recognition_jobs(10, 3) if j.user_id == 'owner')
    RecognitionPipeline(repository, Recognizer(), Embeddings(), StoredImage()).process_job(job)
    assert repository.get_item(item.id).occasion == 'Work'
    assert repository.get_item(item.id).recognition_status == 'complete'
    assert repository.list_recognition_jobs('owner')[0].status == 'complete'
    assert len(json.loads(repository.recognition_records_path.read_text())) == 2


def test_dry_run_manual_opt_in_limit_and_repeat_do_not_duplicate_jobs(repository, tmp_path):
    add_item(repository, 'manual', recognition_status='manual')
    regular = add_item(repository, 'regular')
    add_item(repository, 'third')
    before = repository.items_path.read_bytes()
    preview = reset_user_recognition(repository, 'owner', dry_run=True, limit=1, backup_dir=tmp_path/'backups')
    assert preview['item_ids'] == [regular.id]
    assert preview['skipped'] == {'manual':1, 'limit':1}
    assert repository.items_path.read_bytes() == before
    assert not (tmp_path/'backups').exists()
    assert repository.list_recognition_jobs('owner') == []
    for _ in range(2):
        result = reset_user_recognition(repository, 'owner', include_manual=True, backup_dir=tmp_path/'backups')
        assert len(result['queued_item_ids']) == 3
        assert len(repository.list_recognition_jobs('owner')) == 3


def test_targeted_status_reset_clears_label_confirmation(repository, tmp_path):
    queued = add_item(
        repository, 'queued', recognition_status='queued',
        metadata={'label_confirmation': {'labels': {'category': 'Dresses'}}, 'keep': True},
    )
    complete = add_item(repository, 'complete', recognition_status='complete')

    report = reset_user_recognition(
        repository, 'owner', include_manual=True, statuses={'queued'},
        backup_dir=tmp_path/'backups',
    )

    assert report['queued_item_ids'] == [queued.id]
    assert report['skipped'] == {'status': 1}
    updated = repository.get_item(queued.id, 'owner')
    assert 'label_confirmation' not in updated.metadata
    assert updated.metadata['keep'] is True
    assert repository.get_item(complete.id, 'owner') == complete


def test_processing_job_blocks_all_mutations(repository, tmp_path):
    item = add_item(repository)
    add_job(repository, item, 'processing')
    before = repository.items_path.read_bytes()
    assert reset_user_recognition(repository, 'owner', dry_run=True)['processing_jobs'] == 1
    with pytest.raises(ValueError, match='processing jobs'):
        reset_user_recognition(repository, 'owner', backup_dir=tmp_path/'backups')
    assert repository.items_path.read_bytes() == before
    assert not (tmp_path/'backups').exists()


def test_enqueue_failure_restores_original_item_and_job(repository, tmp_path, monkeypatch):
    item = add_item(repository)
    old = add_job(repository, item, 'failed')
    original_create = repository.create_recognition_job
    def fail_new_job(job):
        if job.id != old.id:
            raise OSError('test outage')
        return original_create(job)
    monkeypatch.setattr(repository, 'create_recognition_job', fail_new_job)
    with pytest.raises(RuntimeError, match='Reset stopped'):
        reset_user_recognition(repository, 'owner', backup_dir=tmp_path/'backups')
    assert repository.get_item(item.id) == item
    assert repository.list_recognition_jobs('owner') == [old]
    progress = json.loads(next((tmp_path/'backups').glob('*/result.json')).read_text())
    assert progress['rollback'] == 'restored_failed_item'


def test_unknown_user_and_cli_validation_do_not_mutate(repository, tmp_path):
    add_item(repository)
    before = repository.items_path.read_bytes()
    assert reset_user_recognition(repository, 'missing', backup_dir=tmp_path/'backups')['selected'] == 0
    assert repository.items_path.read_bytes() == before
    for argv in [[], ['--user-id','bad'], ['--user-id','00000000-0000-4000-8000-000000000001','--limit','0']]:
        with pytest.raises(SystemExit) as error:
            main(argv)
        assert error.value.code == 2


def test_supabase_reset_reads_all_pages_and_always_filters_owner():
    rows = [dict(id=str(i),user_id='owner') for i in range(5)]
    calls = []
    class Client:
        def table(self, table): return self
        def select(self, columns): assert columns == '*'; return self
        def eq(self, key, value): assert (key,value) == ('user_id','owner'); return self
        def order(self, key): assert key == 'id'; return self
        def range(self, start, end): self.start = start; calls.append(start); return self
        def execute(self): return SimpleNamespace(data=rows[self.start:self.start+2])
    repo = object.__new__(SupabaseClosetRepository)
    repo.client = Client()
    assert repo._all_user_rows('clothing_items','owner') == rows
    assert calls == [0,2,4,5]


@pytest.mark.parametrize('flags,expected_mode,expected_count', [
    ([], 'keep-manual', 1),
    (['--keep-manual'], 'keep-manual', 1),
    (['--include-manual'], 'reset-all', 2),
])
def test_cli_modes_preview_correct_scope(repository, monkeypatch, capsys, flags, expected_mode, expected_count):
    user_id = '00000000-0000-4000-8000-000000000001'
    add_item(repository, 'manual', user_id, recognition_status='manual')
    add_item(repository, 'automatic', user_id)
    monkeypatch.setattr('tools.admin.reset_recognition.build_closet_repository', lambda: repository)
    assert main(['--user-id', user_id, '--dry-run', *flags]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['mode'] == expected_mode
    assert report['selected'] == expected_count
    assert repository.list_recognition_jobs(user_id) == []


def test_cli_rejects_conflicting_modes():
    with pytest.raises(SystemExit) as error:
        main(['--user-id', '00000000-0000-4000-8000-000000000001', '--keep-manual', '--include-manual'])
    assert error.value.code == 2
