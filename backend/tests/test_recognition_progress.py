import json
from pathlib import Path

from app.models.domain import ClothingItemRecord, RecognitionJobRecord
from tools.admin.recognition_progress import batch_progress, find_run, format_progress
from tools.admin.reset_recognition import reset_user_recognition


def batch(repository, tmp_path):
    repository.add_item(ClothingItemRecord(id='one',user_id='owner',category='Tops',image_url='https://example.test/a.jpg'))
    result=reset_user_recognition(repository,'owner',backup_dir=tmp_path/'runs')
    path=Path(result['backup']).parent/'result.json'
    return path, repository.list_recognition_jobs('owner')[0]


def test_watch_reports_only_exact_batch_and_distinguishes_retry_and_failure(repository, tmp_path):
    path, job = batch(repository,tmp_path)
    assert batch_progress(repository,'owner',path)['queued']==1
    repository.create_recognition_job(RecognitionJobRecord(user_id='owner',clothing_item_id='unrelated',filename='other.jpg',image_url='https://example.test/other.jpg'))
    repository.fail_recognition_job(job.id,'temporary',max_attempts=3)
    progress=batch_progress(repository,'owner',path)
    assert progress['retrying']==1 and progress['state']=='running'
    repository.fail_recognition_job(job.id,'permanent',max_attempts=0)
    progress=batch_progress(repository,'owner',path)
    assert progress['failed']==1 and progress['state']=='needs_attention'
    repository.complete_recognition_job(job.id)
    progress=batch_progress(repository,'owner',path)
    assert progress['state']=='complete' and progress['complete']==1
    assert '全部处理完成' in format_progress(progress)


def test_legacy_batch_without_job_ids_works_for_current_user_run(repository,tmp_path):
    path, job = batch(repository,tmp_path)
    data=json.loads(path.read_text())
    data.pop('queued_job_ids')
    data.pop('enqueue_complete')
    path.write_text(json.dumps(data))
    repository.complete_recognition_job(job.id)
    assert batch_progress(repository,'owner',path)['state']=='complete'
    assert find_run(tmp_path/'runs','owner')==path


def test_missing_old_job_never_counts_new_reset_as_old_completion(repository,tmp_path):
    path, old_job=batch(repository,tmp_path)
    old_data=json.loads(path.read_text())
    old_data.pop('queued_job_ids')
    path.write_text(json.dumps(old_data))
    repository.delete_recognition_jobs_for_item('one','owner')
    new_job=repository.create_recognition_job(RecognitionJobRecord(user_id='owner',clothing_item_id='one',filename='new.jpg',image_url='https://example.test/new.jpg',status='complete',created_at='2099-01-01T00:00:00+00:00'))
    result=batch_progress(repository,'owner',path)
    assert result['missing']==1 and result['state']=='needs_attention'


def test_partial_reset_does_not_report_all_done(repository,tmp_path):
    path, job=batch(repository,tmp_path)
    data=json.loads(path.read_text())
    data.update(selected=2, failed_item_id='two', enqueue_complete=False)
    path.write_text(json.dumps(data))
    repository.complete_recognition_job(job.id)
    progress=batch_progress(repository,'owner',path)
    assert progress['not_queued']==1 and progress['state']=='needs_attention'
