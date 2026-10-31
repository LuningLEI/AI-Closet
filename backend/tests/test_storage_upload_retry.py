import asyncio
from io import BytesIO
import httpx
import pytest
from starlette.datastructures import UploadFile
from app.services.storage_service import StorageService

@pytest.mark.parametrize('failure',[httpx.WriteError,httpx.ReadTimeout,httpx.RemoteProtocolError])
def test_upload_retries_identical_content_and_path(monkeypatch,failure):
    service=StorageService();service.supabase=object();calls=[]
    async def no_sleep(_):pass
    monkeypatch.setattr('app.services.storage_service.asyncio.sleep',no_sleep)
    def upload(path,content,kind):
        calls.append((path,content,kind))
        if len(calls)==1:raise failure('connection lost')
    monkeypatch.setattr(service,'_upload_remote',upload)
    result=asyncio.run(service.store_image(UploadFile(BytesIO(b'photo'),filename='edit.jpg'),'owner'))
    assert len(calls)==2 and calls[0]==calls[1]
    assert result['image_path']==calls[0][0] and calls[0][1]==b'photo'

@pytest.mark.parametrize('error,expected_calls',[(httpx.WriteError('broken'),3),(ValueError('invalid upload'),1)])
def test_upload_retry_is_bounded_and_only_for_transport(monkeypatch,error,expected_calls):
    service=StorageService();service.supabase=object();calls=[]
    async def no_sleep(_):pass
    monkeypatch.setattr('app.services.storage_service.asyncio.sleep',no_sleep)
    def upload(*args):
        calls.append(args);raise error
    monkeypatch.setattr(service,'_upload_remote',upload)
    with pytest.raises(type(error)):
        asyncio.run(service.store_image(UploadFile(BytesIO(b'photo'),filename='edit.jpg'),'owner'))
    assert len(calls)==expected_calls

def test_remote_upload_uses_isolated_client_and_idempotent_path(monkeypatch):
    service=StorageService();requests=[];options=[];real_client=httpx.Client
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json={'Key':'test/owner/unique.jpg','Id':'object-id'})
    def client(**kwargs):
        options.append(kwargs)
        return real_client(transport=httpx.MockTransport(handle),**kwargs)
    monkeypatch.setattr('app.services.storage_service.httpx.Client',client)
    from types import SimpleNamespace
    monkeypatch.setattr('app.services.storage_service.settings', SimpleNamespace(
        supabase_url='https://storage.test',supabase_service_role_key='test-key',supabase_key=''))
    service._upload_remote('owner/unique.jpg',b'photo','image/jpeg')
    assert options[0]['http2'] is False
    assert requests[0].headers['x-upsert']=='true'
    assert requests[0].url.path.endswith('/owner/unique.jpg')
    assert b'photo' in requests[0].content
