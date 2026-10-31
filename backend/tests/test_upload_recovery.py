import asyncio
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from starlette.datastructures import UploadFile

from app.services.upload_service import UploadService


class Storage:
    def __init__(self):
        self.paths = []

    async def store_image(self, file, user_id, object_id=None):
        path = f'{user_id}/{object_id or "legacy"}.jpg'
        self.paths.append(path)
        return {'image_path': path, 'image_url': path}

    def signed_image_url(self, path):
        return None


def upload(service, key='upload-1', owner='owner', content=b'photo'):
    return asyncio.run(service.queue_clothing_item(
        owner, UploadFile(BytesIO(content), filename='image.jpg'), 'http://test', key))


def test_retry_reuses_item_and_job(repository):
    storage = Storage()
    service = UploadService(repository, storage)
    first = upload(service)
    second = upload(service)
    assert first.id == second.id
    assert len(repository.list_items('owner')) == 1
    assert len(storage.paths) == 1
    assert len(repository._read_json_records(repository.recognition_jobs_path,
        __import__('app.models.domain', fromlist=['RecognitionJobRecord']).RecognitionJobRecord)) == 1


def test_identity_is_scoped_to_owner_selection_and_bytes(repository):
    service = UploadService(repository, Storage())
    results = [upload(service), upload(service, owner='other'),
               upload(service, key='new-selection'), upload(service, content=b'changed')]
    assert len({item.id for item in results}) == 4


def test_lost_database_commit_response_is_reconciled(repository, monkeypatch):
    original = repository.create_item_with_records
    def commit_then_disconnect(*args, **kwargs):
        original(*args, **kwargs)
        raise httpx.ReadTimeout('response lost')
    monkeypatch.setattr(repository, 'create_item_with_records', commit_then_disconnect)
    item = upload(UploadService(repository, Storage()))
    assert repository.get_item(item.id, 'owner') is not None


def test_precommit_failure_reuses_storage_path_on_retry(repository, monkeypatch):
    storage = Storage()
    service = UploadService(repository, storage)
    original = repository.create_item_with_records
    def disconnected(*args, **kwargs):
        raise httpx.ConnectError('database offline')
    monkeypatch.setattr(repository, 'create_item_with_records', disconnected)
    with pytest.raises(httpx.ConnectError):
        upload(service)
    monkeypatch.setattr(repository, 'create_item_with_records', original)
    upload(service)
    assert len(storage.paths) == 2
    assert storage.paths[0] == storage.paths[1]


def test_concurrent_same_upload_creates_one_item(repository):
    service = UploadService(repository, Storage())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: upload(service), range(2)))
    assert results[0].id == results[1].id
    assert len(repository.list_items('owner')) == 1


def test_worker_survives_claim_and_failure_recording_disconnect(monkeypatch):
    import workers.recognition as worker
    calls = []
    class Stop(Exception): pass
    class Repo:
        def claim_recognition_jobs(self, **kwargs):
            calls.append('claim')
            if calls.count('claim') == 1:
                raise httpx.ConnectError('offline')
            return [SimpleNamespace(id='job', user_id='owner', attempts=1, filename='photo')]
    class Pipeline:
        def __init__(self, repo): pass
        def process_job(self, job):
            calls.append('process')
            raise httpx.ConnectError('cannot record failure')
    def sleep(_):
        if 'process' in calls: raise Stop()
    monkeypatch.setattr(worker, 'build_closet_repository', Repo)
    monkeypatch.setattr(worker, 'RecognitionPipeline', Pipeline)
    monkeypatch.setattr(worker.time, 'sleep', sleep)
    with pytest.raises(Stop): worker.run_worker()
    assert calls == ['claim', 'claim', 'process']


def test_batch_all_failed_returns_per_file_results_and_accepts_retry_ids(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api import dependencies as routes
    from app.api.routes import items as item_routes
    seen = []
    monkeypatch.setattr(routes, 'mutation_user_id', lambda request: 'owner')
    async def fail(request, file, upload_id=None):
        seen.append(upload_id)
        raise httpx.ConnectError('temporarily offline')
    monkeypatch.setattr(item_routes, 'queue_uploaded_item', fail)
    client = TestClient(app)
    response = client.post('/api/v1/items/upload-batch',
        files=[('files', ('one.jpg', b'one', 'image/jpeg'))],
        data={'upload_ids': '["stable-key"]'})
    assert response.status_code == 200
    assert response.json()['items'] == []
    assert response.json()['errors'][0]['filename'] == 'one.jpg'
    assert seen == ['stable-key']
    response = client.post('/api/v1/items/upload-batch',
        files=[('files', ('one.jpg', b'one', 'image/jpeg'))],
        data={'upload_ids': '[]'})
    assert response.status_code == 400
    assert seen == ['stable-key']
