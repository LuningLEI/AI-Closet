from __future__ import annotations

import traceback

from fastapi import HTTPException
from fastapi import UploadFile

from app.core.constants import DEFAULT_SEASON, PIPELINE_NAME, RecognitionSource, RecognitionStatus
from app.core.versions import CLOTHING_ANALYSIS_VERSION, ITEM_FEATURE_VERSION, MANUAL_TAXONOMY_EDIT_VERSION, TAXONOMY_VERSION
from app.models.api import ClothingItemUpdateRequest
from app.models.domain import ClothingAnalysis, ClothingItemRecord, RecognitionJobRecord, RecognitionRecord
from app.repositories.base import ClosetRepositoryProtocol
from app.services.embedding_service import EmbeddingService, item_embedding_text
from app.services.recognition_pipeline import feature_vector
from app.services.response_signing import absolute_url


class ItemService:
    def __init__(self, repository: ClosetRepositoryProtocol, embedding_service: EmbeddingService, storage_service=None) -> None:
        self.repository = repository
        self.embedding_service = embedding_service
        self.storage_service = storage_service

    def update_item(self, user_id: str, item_id: str, payload: ClothingItemUpdateRequest) -> ClothingItemRecord:
        existing_item = self.repository.get_item(item_id, user_id)
        if not existing_item:
            raise HTTPException(status_code=404, detail="Clothing item not found.")

        analysis = self._manual_analysis(payload)
        updates = {
            "analysis_version": analysis.analysis_version,
            "taxonomy_version": analysis.taxonomy_version,
            "feature_version": ITEM_FEATURE_VERSION,
            "recognition_status": RecognitionStatus.MANUAL,
            "category": analysis.category,
            "subtype": analysis.subtype,
            "color": analysis.color,
            "season": ", ".join(analysis.seasons),
            "style": analysis.style,
            "occasion": analysis.occasion,
            "recognition_source": RecognitionSource.MANUAL_EDIT,
            "recognition_summary": analysis.summary,
            "recognition_confidence": None,
            "recognition_tags": analysis.model_dump(),
            "feature_vector": feature_vector(analysis),
            "metadata": {
                **(existing_item.metadata or {}),
                "recognition_status": RecognitionStatus.MANUAL,
                "manual_override": True,
            },
        }
        item_for_embedding = existing_item.model_copy(
            update={
                "category": analysis.category,
                "subtype": analysis.subtype,
                "color": analysis.color,
                "season": ", ".join(analysis.seasons),
                "style": analysis.style,
                "occasion": analysis.occasion,
                "recognition_source": RecognitionSource.MANUAL_EDIT,
                "recognition_summary": analysis.summary,
            }
        )
        updates["semantic_vector"] = self.embedding_service.create_embedding(item_embedding_text(item_for_embedding))
        updated_item = self.repository.update_item(item_id, updates, user_id)
        if not updated_item:
            raise HTTPException(status_code=404, detail="Clothing item not found.")

        self.repository.add_recognition_record(
            RecognitionRecord(
                user_id=user_id,
                clothing_item_id=item_id,
                provider=RecognitionSource.MANUAL_EDIT,
                model_name="user-correction",
                prompt_version=MANUAL_TAXONOMY_EDIT_VERSION,
                analysis_version=analysis.analysis_version,
                taxonomy_version=analysis.taxonomy_version,
                confidence=None,
                category=analysis.category,
                subtype=analysis.subtype,
                color=analysis.color,
                seasons=analysis.seasons,
                style=analysis.style,
                occasion=analysis.occasion,
                normalized_payload=analysis.model_dump(),
                raw_payload={"previous_item": existing_item.model_dump(), "manual_payload": payload.model_dump()},
            )
        )
        return updated_item

    def delete_item(self, user_id: str, item_id: str) -> ClothingItemRecord | None:
        print("[item_service.delete_item] lookup", {"item_id": item_id, "user_id": user_id})
        deleted_item = self.repository.delete_item(item_id, user_id)
        if not deleted_item:
            print("[item_service.delete_item] not_found", {"item_id": item_id, "user_id": user_id})
            raise HTTPException(status_code=404, detail="Clothing item not found.")
        print(
            "[item_service.delete_item] deleted",
            {
                "item_id": deleted_item.id,
                "user_id": deleted_item.user_id,
                "image_path": deleted_item.image_path,
            },
        )
        if self.storage_service:
            self.storage_service.delete_image(deleted_item.image_path)
        return deleted_item

    async def replace_item_image(
        self,
        user_id: str,
        item_id: str,
        file: UploadFile,
        base_url: str,
    ) -> ClothingItemRecord:
        try:
            print("[item_service.replace_item_image] lookup", {"item_id": item_id, "user_id": user_id})
            existing_item = self.repository.get_item(item_id, user_id)
            if not existing_item:
                print("[item_service.replace_item_image] not_found", {"item_id": item_id, "user_id": user_id})
                raise HTTPException(status_code=404, detail="Clothing item not found.")
            print(
                "[item_service.replace_item_image] existing_item",
                {
                    "id": existing_item.id,
                    "user_id": existing_item.user_id,
                    "image_path": existing_item.image_path,
                    "image_url": existing_item.image_url,
                    "recognition_status": existing_item.recognition_status,
                },
            )
            if not self.storage_service:
                raise HTTPException(status_code=500, detail="Storage service is not configured.")

            previous_image_path = existing_item.image_path
            stored = await self.storage_service.store_image(file, user_id)
            print(
                "[item_service.replace_item_image] stored_image",
                {
                    "item_id": item_id,
                    "user_id": user_id,
                    "stored_image_path": stored.get("image_path"),
                    "stored_image_url": stored.get("image_url"),
                },
            )
            image_url = stored["image_url"]
            response_image_url = absolute_url(base_url, self.storage_service.signed_image_url(stored.get("image_path"))) or image_url

            self.repository.delete_recognition_jobs_for_item(item_id, user_id)
            updated_item = self.repository.update_item(
                item_id,
                {
                    "image_url": image_url,
                    "image_path": stored.get("image_path"),
                    "analysis_version": CLOTHING_ANALYSIS_VERSION,
                    "taxonomy_version": TAXONOMY_VERSION,
                    "feature_version": ITEM_FEATURE_VERSION,
                    "recognition_status": RecognitionStatus.QUEUED,
                    "recognition_source": RecognitionSource.ANALYZING,
                    "recognition_summary": "Vision analysis is running.",
                    "recognition_confidence": None,
                    "recognition_tags": None,
                    "feature_vector": None,
                    "semantic_vector": None,
                    "metadata": {
                        **(existing_item.metadata or {}),
                        "pipeline": PIPELINE_NAME,
                        "recognition_status": RecognitionStatus.QUEUED,
                        "image_replaced": True,
                    },
                },
                user_id,
            )
            if not updated_item:
                print("[item_service.replace_item_image] update_not_found", {"item_id": item_id, "user_id": user_id})
                raise HTTPException(status_code=404, detail="Clothing item not found.")
            print(
                "[item_service.replace_item_image] updated_item",
                {
                    "id": updated_item.id,
                    "user_id": updated_item.user_id,
                    "image_path": updated_item.image_path,
                    "recognition_status": updated_item.recognition_status,
                },
            )

            self.repository.create_recognition_job(
                RecognitionJobRecord(
                    user_id=user_id,
                    clothing_item_id=updated_item.id,
                    filename=file.filename or "edited-image.jpg",
                    image_url=response_image_url,
                    image_path=stored.get("image_path"),
                )
            )
            print(
                "[item_service.replace_item_image] queued_recognition_job",
                {
                    "item_id": updated_item.id,
                    "user_id": user_id,
                    "filename": file.filename or "edited-image.jpg",
                    "image_path": stored.get("image_path"),
                },
            )

            if previous_image_path and previous_image_path != stored.get("image_path"):
                self.storage_service.delete_image(previous_image_path)
                print(
                    "[item_service.replace_item_image] deleted_previous_image",
                    {
                        "item_id": updated_item.id,
                        "previous_image_path": previous_image_path,
                    },
                )
            return updated_item
        except HTTPException:
            raise
        except Exception as error:
            print(
                "[item_service.replace_item_image] unexpected_error",
                {
                    "item_id": item_id,
                    "user_id": user_id,
                    "filename": file.filename,
                    "content_type": file.content_type,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                },
            )
            raise HTTPException(status_code=500, detail=f"Replace image failed: {type(error).__name__}: {error}") from error

    def _manual_analysis(self, payload: ClothingItemUpdateRequest) -> ClothingAnalysis:
        seasons = [season.strip() for season in payload.season.split(",") if season.strip()]
        return ClothingAnalysis(
            category=payload.category,
            subtype=payload.subtype,
            color=payload.color,
            seasons=seasons or [DEFAULT_SEASON],
            style=payload.style,
            occasion=payload.occasion,
            summary=payload.recognition_summary,
            source=RecognitionSource.MANUAL_EDIT,
            raw_category=payload.category,
            raw_subtype=payload.subtype,
            raw_color=payload.color,
            raw_style=payload.style,
            raw_occasion=payload.occasion,
            raw_seasons=seasons or [DEFAULT_SEASON],
        )
