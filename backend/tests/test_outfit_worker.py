import threading
from workers import outfits as outfit_worker
from app.outfits.config import load_config


def test_consumer_recovers_after_transient_claim_error(monkeypatch):
    stop=threading.Event();calls=[];repos=[]
    config=load_config().model_copy(update={'poll_seconds':0.001})
    def repo():
        value=object();repos.append(value);return value
    def process(library):
        calls.append(library)
        if len(calls)==1:raise ConnectionError('temporary disconnect')
        stop.set();return False
    monkeypatch.setattr(outfit_worker,'load_config',lambda:config)
    monkeypatch.setattr(outfit_worker,'build_closet_repository',repo)
    monkeypatch.setattr(outfit_worker,'build_store',lambda repo:object())
    monkeypatch.setattr(outfit_worker,'process_next',process)
    outfit_worker.consume(stop)
    assert len(calls)==2 and len(repos)==1


def test_stopped_consumer_does_not_claim(monkeypatch):
    stop=threading.Event();stop.set()
    def unexpected():raise AssertionError('No client should be created after stop')
    monkeypatch.setattr(outfit_worker,'build_closet_repository',unexpected)
    outfit_worker.consume(stop)


def test_database_error_logs_action_without_sensitive_payload():
    class APIError(Exception):
        code = 'PGRST205'
    summary = outfit_worker.error_summary(APIError('secret-token https://private/image'))
    assert 'code=PGRST205' in summary
    assert 'migrations_008_then_009' in summary
    assert 'secret-token' not in summary and 'https://' not in summary


def test_unknown_error_code_is_not_logged_verbatim():
    error = RuntimeError('private response')
    error.code = 'secret-token with spaces'
    assert outfit_worker.error_summary(error) == 'type=RuntimeError code=unknown'


def test_validation_error_shows_field_without_rejected_values():
    from pydantic import BaseModel, ConfigDict, ValidationError
    class OldConfig(BaseModel):
        model_config = ConfigDict(extra='forbid')
    try:
        OldConfig.model_validate({'require_shoes': 'secret-token'})
    except ValidationError as error:
        summary = outfit_worker.error_summary(error)
    assert 'require_shoes:extra_forbidden' in summary
    assert 'secret-token' not in summary
    assert 'restart_worker' in summary
