from __future__ import annotations

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

    async def queue_clothing_item(self, user_id: str, file: UploadFile, base_url: str) -> ClothingItemRecord:
        stored = await self.storage_service.store_image(file, user_id)
        image_url = stored["image_url"]
        response_image_url = absolute_url(base_url, self.storage_service.signed_image_url(stored.get("image_path"))) or image_url

        item = ClothingItemRecord(
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
        saved_item = self.repository.add_item(item)
        self.repository.create_recognition_job(
            RecognitionJobRecord(
                user_id=user_id,
                clothing_item_id=saved_item.id,
                filename=file.filename or "upload.jpg",
                image_url=response_image_url,
                image_path=stored.get("image_path"),
            )
        )
        return saved_item
