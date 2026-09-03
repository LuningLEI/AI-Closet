from __future__ import annotations

from pathlib import Path

from app.models.domain import ClothingItemRecord
from app.services.response_signing import ResponseSigningService
from app.services.storage_service import StorageService


class FakeBucket:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls: list[tuple[str, int]] = []
        self.batch_calls: list[tuple[list[str], int]] = []
        self.batch_responses = None

    def create_signed_url(self, image_path: str, expires_in: int):
        self.calls.append((image_path, expires_in))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response

    def create_signed_urls(self, paths: list[str], expires_in: int, options=None):
        del options
        self.batch_calls.append((paths, expires_in))
        if isinstance(self.batch_responses, Exception):
            raise self.batch_responses
        return self.batch_responses or []


class FakeStorageNamespace:
    def __init__(self, bucket: FakeBucket):
        self.bucket = bucket

    def from_(self, _bucket_name: str) -> FakeBucket:
        return self.bucket


class FakeSupabase:
    def __init__(self, bucket: FakeBucket):
        self.storage = FakeStorageNamespace(bucket)


def test_storage_service_caches_signed_url(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.services.storage_service.time.monotonic", lambda: now[0])

    bucket = FakeBucket([{"signedURL": "https://example.com/a.jpg?token=1"}])
    service = StorageService()
    service.supabase = FakeSupabase(bucket)

    first = service.signed_image_url("user-a/a.jpg", expires_in=900)
    second = service.signed_image_url("user-a/a.jpg", expires_in=900)

    assert first == "https://example.com/a.jpg?token=1"
    assert second == first
    assert bucket.calls == [("user-a/a.jpg", 900)]


def test_storage_service_uses_cached_url_when_refresh_fails(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.services.storage_service.time.monotonic", lambda: now[0])

    bucket = FakeBucket(
        [
            {"signedURL": "https://example.com/a.jpg?token=1"},
            OSError(35, "Resource temporarily unavailable"),
        ]
    )
    service = StorageService()
    service.supabase = FakeSupabase(bucket)

    cached = service.signed_image_url("user-a/a.jpg", expires_in=900)
    now[0] = 450.0
    reused = service.signed_image_url("user-a/a.jpg", expires_in=900)

    assert cached == "https://example.com/a.jpg?token=1"
    assert reused == cached
    assert bucket.calls == [("user-a/a.jpg", 900), ("user-a/a.jpg", 900)]


def test_storage_service_negative_caches_failures(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.services.storage_service.time.monotonic", lambda: now[0])

    bucket = FakeBucket(
        [
            OSError(35, "Resource temporarily unavailable"),
            {"signedURL": "https://example.com/a.jpg?token=2"},
        ]
    )
    service = StorageService()
    service.supabase = FakeSupabase(bucket)

    first = service.signed_image_url("user-a/a.jpg", expires_in=900)
    second = service.signed_image_url("user-a/a.jpg", expires_in=900)
    now[0] = 131.0
    third = service.signed_image_url("user-a/a.jpg", expires_in=900)

    assert first is None
    assert second is None
    assert third == "https://example.com/a.jpg?token=2"
    assert bucket.calls == [("user-a/a.jpg", 900), ("user-a/a.jpg", 900)]


def test_response_signing_items_dedupes_paths_and_falls_back_to_local_uploads(tmp_path):
    service = StorageService()
    service.supabase = None
    service.uploads_dir = tmp_path / "uploads"
    service.uploads_dir.mkdir(parents=True, exist_ok=True)

    signer = ResponseSigningService(service)
    image_path = str(service.uploads_dir / "user-a" / "coat.jpg")
    items = [
        ClothingItemRecord(user_id="user-a", image_url="user-a/coat.jpg", image_path=image_path, category="Outerwear"),
        ClothingItemRecord(user_id="user-a", image_url="user-a/coat.jpg", image_path=image_path, category="Outerwear"),
    ]

    signed_items = signer.items(items, "http://127.0.0.1:8000/")

    assert [item.image_url for item in signed_items] == [
        "http://127.0.0.1:8000/uploads/user-a/coat.jpg",
        "http://127.0.0.1:8000/uploads/user-a/coat.jpg",
    ]


def test_storage_service_batch_signs_unique_paths(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.services.storage_service.time.monotonic", lambda: now[0])

    bucket = FakeBucket([])
    bucket.batch_responses = [
        {"signedURL": "https://example.com/a.jpg?token=1"},
        {"signedURL": "https://example.com/b.jpg?token=1"},
    ]
    service = StorageService()
    service.supabase = FakeSupabase(bucket)

    signed = service.signed_image_urls(["user-a/a.jpg", "user-a/b.jpg", "user-a/a.jpg"], expires_in=900)

    assert signed == {
        "user-a/a.jpg": "https://example.com/a.jpg?token=1",
        "user-a/b.jpg": "https://example.com/b.jpg?token=1",
    }
    assert bucket.batch_calls == [(["user-a/a.jpg", "user-a/b.jpg"], 900)]
    assert bucket.calls == []


def test_storage_service_batch_falls_back_to_single_sign_on_missing_entries(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.services.storage_service.time.monotonic", lambda: now[0])

    bucket = FakeBucket([{"signedURL": "https://example.com/b.jpg?token=2"}])
    bucket.batch_responses = [
        {"signedURL": "https://example.com/a.jpg?token=1"},
        {},
    ]
    service = StorageService()
    service.supabase = FakeSupabase(bucket)

    signed = service.signed_image_urls(["user-a/a.jpg", "user-a/b.jpg"], expires_in=900)

    assert signed == {
        "user-a/a.jpg": "https://example.com/a.jpg?token=1",
        "user-a/b.jpg": "https://example.com/b.jpg?token=2",
    }
    assert bucket.batch_calls == [(["user-a/a.jpg", "user-a/b.jpg"], 900)]
    assert bucket.calls == [("user-a/b.jpg", 900)]
