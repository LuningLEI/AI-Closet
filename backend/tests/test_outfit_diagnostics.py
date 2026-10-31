import httpx
import pytest
from app.outfits.diagnostics import OutfitModelError, OutfitValidationError, error_details
from app.outfits.provider import VisionOutfitProvider
from app.outfits.config import load_config
from app.outfits.models import Proposals
from app.outfits.runs import tracked_call


def test_http_error_keeps_only_allowlisted_fields(monkeypatch):
    response = httpx.Response(429, json={'error': {'code': 'insufficient_quota', 'message': 'secret https://private/photo'}}, headers={'x-request-id': 'req_test123'})
    class Client:
        def post(self, *args, **kwargs): return response
    from app.ai.gateway import OpenAICompatibleGateway
    gateway = OpenAICompatibleGateway(api_key='test-secret', client=Client())
    with pytest.raises(OutfitModelError) as caught:
        VisionOutfitProvider(load_config(), storage=object(), gateway=gateway).request('test', 'secret prompt', [], Proposals)
    details = error_details(caught.value)
    assert details['http_status'] == 429
    assert details['provider_code'] == 'insufficient_quota'
    assert details['request_id'] == 'req_test123'
    assert 'secret' not in str(details) + str(caught.value)


def test_unknown_provider_fields_are_redacted():
    details = error_details(OutfitModelError(400, 'sk-secret', 'https://private'))
    assert details['provider_code'] == 'unknown'
    assert 'request_id' not in details
    assert error_details(ValueError('secret input')) == {'type': 'ValueError'}
    assert error_details(OutfitValidationError('invalid_footwear_selection'))['validation_code'] == 'invalid_footwear_selection'


def test_failed_call_records_phase_without_changing_exception():
    class Store:
        def start_call(self, call): self.call = call
        def finish_call(self, cid, changes): self.changes = changes
    store = Store()
    error = OutfitModelError(503, 'server_error')
    def fail(): raise error
    with pytest.raises(OutfitModelError):
        tracked_call(store, {'id':'j','user_id':'u','attempts':3}, {'id':'r','config':{}}, 'generation', 'test', fail, phase='footwear_selection')
    assert store.call['diagnostics']['phase'] == 'footwear_selection'
    assert store.changes['diagnostics'] == error_details(error)
    assert store.changes['diagnostics']['http_status'] == 503


@pytest.mark.parametrize('code', ['credit_balance_exhausted', 'organization_spend_limit_exceeded', 'project_spend_limit_exceeded', 'organization_usage_limit_exceeded', 'slow_down'])
def test_documented_429_codes_are_retained(code):
    assert error_details(OutfitModelError(429, code))['provider_code'] == code
