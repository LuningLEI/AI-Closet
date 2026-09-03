from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.core.constants import (
    SIGNED_IMAGE_URL_CACHE_TTL_SECONDS,
    SIGNED_IMAGE_URL_EXPIRES_SECONDS,
    SIGNED_IMAGE_URL_FAILURE_TTL_SECONDS,
)

try:
    from supabase import create_client
except ImportError:  # pragma: no cover - optional dependency
    create_client = None


@dataclass
class SignedImageURLCacheEntry:
    url: str | None
    refresh_at: float
    expires_at: float


class StorageService:
    def __init__(self) -> None:
        self.bucket_name = settings.supabase_storage_bucket
        self.uploads_dir = settings.uploads_dir
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.supabase = None
        self.using_remote_storage = False
        self._signed_url_cache: dict[tuple[str, int], SignedImageURLCacheEntry] = {}

        supabase_key = settings.supabase_service_role_key or settings.supabase_key
        if create_client and settings.supabase_url and supabase_key:
            self.supabase = create_client(str(settings.supabase_url), supabase_key)
            self.using_remote_storage = True

    async def store_image(self, file: UploadFile, user_id: str | None = None) -> dict[str, str]:
        extension = Path(file.filename or "upload.jpg").suffix or ".jpg"
        filename = f"{uuid4()}{extension.lower()}"
        storage_path = f"{user_id}/{filename}" if user_id else filename
        return await self._store_upload(file, storage_path)

    async def store_profile_avatar(self, file: UploadFile, user_id: str) -> dict[str, str]:
        extension = Path(file.filename or "avatar.jpg").suffix or ".jpg"
        filename = f"profile/avatar-{uuid4()}{extension.lower()}"
        return await self._store_upload(file, f"{user_id}/{filename}")

    async def _store_upload(self, file: UploadFile, storage_path: str) -> dict[str, str]:
        file_content = await file.read()

        if self.supabase:
            self.supabase.storage.from_(self.bucket_name).upload(
                storage_path,
                file_content,
                file_options={"content-type": file.content_type or "image/jpeg"},
            )
            return {"image_url": storage_path, "image_path": storage_path}

        output_path = self.uploads_dir / storage_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(file_content)
        return {"image_url": f"/uploads/{storage_path}", "image_path": str(output_path)}

    def signed_image_url(self, image_path: str | None, expires_in: int = SIGNED_IMAGE_URL_EXPIRES_SECONDS) -> str | None:
        if not image_path:
            return None
        if not self.supabase:
            return self.fallback_image_url(image_path)

        cache_key = (image_path, expires_in)
        now = time.monotonic()
        cached = self._signed_url_cache.get(cache_key)
        if cached and now < cached.refresh_at:
            return cached.url

        try:
            response = self.supabase.storage.from_(self.bucket_name).create_signed_url(image_path, expires_in)
            signed_url = None
            if isinstance(response, dict):
                signed_url = self._absolute_signed_url(response.get("signedURL") or response.get("signedUrl") or response.get("signed_url"))
            data = getattr(response, "data", None)
            if not signed_url and isinstance(data, dict):
                signed_url = self._absolute_signed_url(data.get("signedURL") or data.get("signedUrl") or data.get("signed_url"))
            if signed_url:
                self._signed_url_cache[cache_key] = SignedImageURLCacheEntry(
                    url=signed_url,
                    refresh_at=now + self._success_cache_ttl(expires_in),
                    expires_at=now + max(expires_in, 1),
                )
                return signed_url
        except Exception as error:
            if cached and cached.url and now < cached.expires_at:
                print("SIGNED IMAGE URL FAILED, USING CACHED URL:", image_path, error)
                return cached.url
            print("SIGNED IMAGE URL FAILED:", image_path, error)

        self._signed_url_cache[cache_key] = SignedImageURLCacheEntry(
            url=None,
            refresh_at=now + SIGNED_IMAGE_URL_FAILURE_TTL_SECONDS,
            expires_at=now + SIGNED_IMAGE_URL_FAILURE_TTL_SECONDS,
        )
        return None

    def signed_image_urls(
        self,
        image_paths: list[str | None],
        expires_in: int = SIGNED_IMAGE_URL_EXPIRES_SECONDS,
    ) -> dict[str, str]:
        signed_urls: dict[str, str] = {}
        unique_paths: list[str] = []
        seen: set[str] = set()
        now = time.monotonic()

        for image_path in image_paths:
            if not image_path or image_path in seen:
                continue
            seen.add(image_path)
            cache_key = (image_path, expires_in)
            cached = self._signed_url_cache.get(cache_key)
            if cached and now < cached.refresh_at:
                if cached.url:
                    signed_urls[image_path] = cached.url
                continue
            unique_paths.append(image_path)

        if not unique_paths:
            return signed_urls

        if self.supabase:
            signed_urls.update(self._batch_signed_image_urls(unique_paths, expires_in))
        else:
            for image_path in unique_paths:
                signed_url = self.signed_image_url(image_path, expires_in=expires_in)
                if signed_url:
                    signed_urls[image_path] = signed_url
        return signed_urls

    def delete_image(self, image_path: str | None) -> None:
        if not image_path:
            return
        if self.supabase:
            try:
                self.supabase.storage.from_(self.bucket_name).remove([image_path])
            except Exception as error:
                print("DELETE IMAGE FAILED:", image_path, error)
            return

        path = Path(image_path)
        if not path.is_absolute():
            path = self.uploads_dir / path
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            print("DELETE IMAGE FAILED:", image_path, error)

    def _absolute_signed_url(self, signed_url: str | None) -> str | None:
        if not signed_url:
            return None
        if signed_url.startswith("http://") or signed_url.startswith("https://"):
            return signed_url
        if signed_url.startswith("/") and settings.supabase_url:
            return str(settings.supabase_url).rstrip("/") + signed_url
        return signed_url

    def fallback_image_url(self, image_path: str | None) -> str | None:
        if not image_path:
            return None
        if image_path.startswith("http://") or image_path.startswith("https://"):
            return image_path
        if not self.supabase:
            path = Path(image_path)
            if path.is_absolute():
                try:
                    relative_path = path.relative_to(self.uploads_dir)
                    return f"/uploads/{relative_path.as_posix()}"
                except ValueError:
                    return image_path
            return f"/uploads/{image_path.lstrip('/')}"
        return None

    def _success_cache_ttl(self, expires_in: int) -> float:
        return float(max(1, min(SIGNED_IMAGE_URL_CACHE_TTL_SECONDS, max(1, expires_in - 60))))

    def _batch_signed_image_urls(self, image_paths: list[str], expires_in: int) -> dict[str, str]:
        now = time.monotonic()
        signed_urls: dict[str, str] = {}

        try:
            responses = self.supabase.storage.from_(self.bucket_name).create_signed_urls(image_paths, expires_in)
            for image_path, response in zip(image_paths, responses):
                signed_url = self._signed_url_from_response(response)
                if signed_url:
                    self._signed_url_cache[(image_path, expires_in)] = SignedImageURLCacheEntry(
                        url=signed_url,
                        refresh_at=now + self._success_cache_ttl(expires_in),
                        expires_at=now + max(expires_in, 1),
                    )
                    signed_urls[image_path] = signed_url
        except Exception as error:
            print("BATCH SIGNED IMAGE URL FAILED:", {"count": len(image_paths), "error": str(error)})

        if len(signed_urls) == len(image_paths):
            return signed_urls

        for image_path in image_paths:
            if image_path in signed_urls:
                continue
            signed_url = self.signed_image_url(image_path, expires_in=expires_in)
            if signed_url:
                signed_urls[image_path] = signed_url
        return signed_urls

    def _signed_url_from_response(self, response: Any) -> str | None:
        if isinstance(response, dict):
            return self._absolute_signed_url(
                response.get("signedURL") or response.get("signedUrl") or response.get("signed_url")
            )
        data = getattr(response, "data", None)
        if isinstance(data, dict):
            return self._absolute_signed_url(
                data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
            )
        for attribute in ("signedURL", "signedUrl", "signed_url"):
            value = getattr(response, attribute, None)
            if value:
                return self._absolute_signed_url(value)
        return None
