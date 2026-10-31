from __future__ import annotations

from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from fastapi import UploadFile

from app.core.constants import (
    DEFAULT_CATEGORY,
    DEFAULT_COLOR,
    DEFAULT_OCCASION,
    DEFAULT_SEASON,
    DEFAULT_STYLE,
    PIPELINE_NAME,
    RecognitionSource,
    RecognitionStatus,
)
from app.core.versions import CLOTHING_ANALYSIS_VERSION, ITEM_FEATURE_VERSION, TAXONOMY_VERSION
from app.models.domain import ClothingItemRecord, RecognitionJobRecord
from app.repositories.base import ClosetRepositoryProtocol
from app.services.response_signing import absolute_url
from app.services.storage_service import StorageService


class UploadService:
    def __init__(self, repository: ClosetRepositoryProtocol, storage_service: StorageService) -> None:
        self.repository = repository
        self.storage_service = storage_service

    async def queue_clothing_item(self, user_id: str, file: UploadFile, base_url: str, upload_id: str | None = None) -> ClothingItemRecord:
        # Bind retries to both owner and bytes. A new selection gets a new upload ID.
        # No distributed lock is needed: the item primary key arbitrates concurrent commits.
        item_id = None
        if upload_id:
            digest = sha256(await file.read()).hexdigest()
            await file.seek(0)
            item_id = str(uuid5(NAMESPACE_URL, f"closet-upload:{user_id}:{upload_id}:{digest}"))
            existing = self.repository.get_item(item_id, user_id)
            if existing is not None:
                return existing
        if item_id:
            stored = await self.storage_service.store_image(file, user_id, object_id=item_id)
        else:
            stored = await self.storage_service.store_image(file, user_id)
        image_url = stored["image_url"]
        response_image_url = absolute_url(base_url, self.storage_service.signed_image_url(stored.get("image_path"))) or image_url

        item = ClothingItemRecord(
            **({"id": item_id} if item_id else {}),
            user_id=user_id,
            image_url=image_url,
            image_path=stored.get("image_path"),
            analysis_version=CLOTHING_ANALYSIS_VERSION,
            taxonomy_version=TAXONOMY_VERSION,
            feature_version=ITEM_FEATURE_VERSION,
            recognition_status=RecognitionStatus.QUEUED,
            category=DEFAULT_CATEGORY,
            color=DEFAULT_COLOR,
            season=DEFAULT_SEASON,
            style=DEFAULT_STYLE,
            occasion=DEFAULT_OCCASION,
            recognition_source=RecognitionSource.ANALYZING,
            recognition_summary="Vision analysis is running.",
            metadata={"pipeline": PIPELINE_NAME, "recognition_status": RecognitionStatus.QUEUED},
        )
        job = RecognitionJobRecord(
                user_id=user_id,
                clothing_item_id=item.id,
                filename=file.filename or "upload.jpg",
                image_url=response_image_url,
                image_path=stored.get("image_path"),
            )
        try:
            return self.repository.create_item_with_records(item, job=job)
        except Exception:
            # Includes a lost commit response and a competing successful insert.
            # Never delete the object here: an uncertain commit may already reference it.
            if item_id:
                existing = self.repository.get_item(item_id, user_id)
                if existing is not None:
                    return existing
            raise
