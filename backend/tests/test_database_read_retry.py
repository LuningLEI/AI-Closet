from types import SimpleNamespace
import httpx
import pytest
from app.repositories.read_retry import execute_read, DatabaseReadUnavailable


def test_transient_read_error_rebuilds_request_and_recovers(monkeypatch):
    monkeypatch.setattr('app.repositories.read_retry.time.sleep', lambda _: None)
    calls = []
    def build():
        calls.append(1)
        def execute():
            if len(calls) < 3:
                raise httpx.ReadError('private connection details')
            return 'result'
        return SimpleNamespace(execute=execute)
    assert execute_read(build) == 'result'
    assert len(calls) == 3


def test_persistent_transport_failure_is_bounded_and_safe(monkeypatch):
    monkeypatch.setattr('app.repositories.read_retry.time.sleep', lambda _: None)
    calls = []
    def build():
        calls.append(1)
        def execute():
            raise httpx.RemoteProtocolError('secret URL')
        return SimpleNamespace(execute=execute)
    with pytest.raises(DatabaseReadUnavailable) as error:
        execute_read(build)
    assert 'secret' not in str(error.value)
    assert len(calls) == 3


def test_does_not_retry_validation_error():
    calls = []
    def build():
        calls.append(1)
        def execute():
            raise ValueError('invalid data')
        return SimpleNamespace(execute=execute)
    with pytest.raises(ValueError):
        execute_read(build)
    assert len(calls) == 1


def test_item_lookup_preserves_user_scope_across_retry(monkeypatch):
    from app.repositories.supabase_closet_repository import SupabaseClosetRepository
    monkeypatch.setattr('app.repositories.read_retry.time.sleep', lambda _: None)
    requests = []
    class Query:
        def __init__(self):
            self.filters = []
            requests.append(self)
        def select(self, columns): return self
        def eq(self, key, value):
            self.filters.append((key, value))
            return self
        def limit(self, value):
            assert value == 1
            return self
        def execute(self):
            if len(requests) == 1: raise httpx.ReadError('interrupted')
            return SimpleNamespace(data=[])
    repo = SupabaseClosetRepository.__new__(SupabaseClosetRepository)
    repo.table_name = 'clothing_items'
    repo.client = SimpleNamespace(table=lambda name: Query())
    assert repo.get_item('item-id', 'owner-id') is None
    assert len(requests) == 2
    assert all(q.filters == [('id', 'item-id'), ('user_id', 'owner-id')] for q in requests)


def test_exhausted_reads_return_actionable_503():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.main import database_read_unavailable
    app = FastAPI()
    app.add_exception_handler(DatabaseReadUnavailable, database_read_unavailable)
    @app.get('/item')
    def item():
        raise DatabaseReadUnavailable('private details')
    response = TestClient(app).get('/item')
    assert response.status_code == 503
    assert response.headers['Retry-After'] == '2'
    assert 'Please try again' in response.json()['detail']
    assert 'private' not in response.text
