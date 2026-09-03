from __future__ import annotations

from app.core.config import settings
from app.core.constants import (
    CATEGORY_VECTOR_GROUPS,
    CORE_CATEGORY_VECTOR_LABELS,
    CORE_STYLE_VECTOR_LABELS,
    PIPELINE_NAME,
    VISION_IMAGE_URL_EXPIRES_SECONDS,
    RecognitionSource,
    RecognitionStatus,
)
from app.core.observability import log_event
from app.core.versions import HEURISTIC_FALLBACK_MODEL_VERSION, ITEM_FEATURE_VERSION, TAXONOMY_PROMPT_VERSION
from app.models.domain import ClothingItemRecord, ItemFeatureSnapshot, RecognitionJobRecord, RecognitionRecord
from app.services.embedding_service import EmbeddingService, item_embedding_text
from app.services.recognition_service import ClothingRecognitionService
from app.services.storage_service import StorageService
from app.services.taxonomy import merge_preferences, user_categories


class RecognitionPipeline:
    def __init__(
        self,
        repository,
        recognition_service: ClothingRecognitionService | None = None,
        embedding_service: EmbeddingService | None = None,
        storage_service: StorageService | None = None,
    ) -> None:
        self.repository = repository
        self.recognition_service = recognition_service or ClothingRecognitionService()
        self.embedding_service = embedding_service or EmbeddingService()
        self.storage_service = storage_service or StorageService()

    def process_job(self, job: RecognitionJobRecord) -> None:
        try:
            image_url = self.storage_service.signed_image_url(job.image_path, expires_in=VISION_IMAGE_URL_EXPIRES_SECONDS) or job.image_url
            preferences = merge_preferences(self.repository.get_preferences(job.user_id).get("preferences", {}))
            analysis = self.recognition_service.analyze(
                job.filename,
                image_url=image_url,
                allowed_categories=user_categories(preferences),
                user_profile=preferences.get("profile", {}),
            )
            item_updates = {
                "analysis_version": analysis.analysis_version,
                "taxonomy_version": analysis.taxonomy_version,
                "feature_version": ITEM_FEATURE_VERSION,
                "recognition_status": RecognitionStatus.COMPLETE,
                "category": analysis.category,
                "subtype": analysis.subtype,
                "color": analysis.color,
                "season": ", ".join(analysis.seasons),
                "style": analysis.style,
                "occasion": analysis.occasion,
                "material": analysis.material,
                "pattern": analysis.pattern,
                "fit": analysis.fit,
                "length": analysis.length,
                "sleeve_length": analysis.sleeve_length,
                "neckline": analysis.neckline,
                "layering_role": analysis.layering_role,
                "warmth_level": analysis.warmth_level,
                "formality_score": analysis.formality_score,
                "recognition_source": analysis.source,
                "recognition_summary": analysis.summary,
                "recognition_confidence": analysis.confidence,
                "recognition_tags": analysis.model_dump(),
                "feature_vector": feature_vector(analysis),
                "metadata": {
                    "pipeline": PIPELINE_NAME,
                    "recognition_status": RecognitionStatus.COMPLETE,
                    "analysis_version": analysis.analysis_version,
                    "taxonomy_version": analysis.taxonomy_version,
                    "feature_version": ITEM_FEATURE_VERSION,
                },
            }
            item_for_embedding = ClothingItemRecord(
                user_id=job.user_id,
                image_url=image_url,
                image_path=job.image_path,
                analysis_version=analysis.analysis_version,
                taxonomy_version=analysis.taxonomy_version,
                feature_version=ITEM_FEATURE_VERSION,
                recognition_status=RecognitionStatus.COMPLETE,
                category=analysis.category,
                subtype=analysis.subtype,
                color=analysis.color,
                season=", ".join(analysis.seasons),
                style=analysis.style,
                occasion=analysis.occasion,
                material=analysis.material,
                pattern=analysis.pattern,
                fit=analysis.fit,
                length=analysis.length,
                sleeve_length=analysis.sleeve_length,
                neckline=analysis.neckline,
                layering_role=analysis.layering_role,
                warmth_level=analysis.warmth_level,
                formality_score=analysis.formality_score,
                recognition_source=analysis.source,
                recognition_summary=analysis.summary,
            )
            item_updates["semantic_vector"] = self.embedding_service.create_embedding(item_embedding_text(item_for_embedding))
            updated_item = self.repository.update_item(job.clothing_item_id, item_updates)

            recognition_record = RecognitionRecord(
                user_id=job.user_id,
                clothing_item_id=job.clothing_item_id,
                provider=analysis.source,
                model_name=settings.openai_vision_model if analysis.source == RecognitionSource.OPENAI_VISION else HEURISTIC_FALLBACK_MODEL_VERSION,
                prompt_version=TAXONOMY_PROMPT_VERSION,
                analysis_version=analysis.analysis_version,
                taxonomy_version=analysis.taxonomy_version,
                confidence=analysis.confidence,
                category=analysis.category,
                subtype=analysis.subtype,
                color=analysis.color,
                seasons=analysis.seasons,
                style=analysis.style,
                occasion=analysis.occasion,
                material=analysis.material,
                pattern=analysis.pattern,
                fit=analysis.fit,
                length=analysis.length,
                sleeve_length=analysis.sleeve_length,
                neckline=analysis.neckline,
                layering_role=analysis.layering_role,
                warmth_level=analysis.warmth_level,
                formality_score=analysis.formality_score,
                normalized_payload=analysis.model_dump(),
                raw_payload={
                    "filename": job.filename,
                    "storage_path": job.image_path,
                    "image_url": image_url,
                    "recognition_job_id": job.id,
                },
            )
            self.repository.add_recognition_record(recognition_record)

            feature_snapshot = ItemFeatureSnapshot(
                user_id=job.user_id,
                clothing_item_id=job.clothing_item_id,
                feature_version=ITEM_FEATURE_VERSION,
                feature_vector=item_updates["feature_vector"],
                extra_features={
                    "category": updated_item.category if updated_item else analysis.category,
                    "subtype": updated_item.subtype if updated_item else analysis.subtype,
                    "color": updated_item.color if updated_item else analysis.color,
                    "style": updated_item.style if updated_item else analysis.style,
                    "occasion": updated_item.occasion if updated_item else analysis.occasion,
                    "season": updated_item.season if updated_item else ", ".join(analysis.seasons),
                    "material": updated_item.material if updated_item else analysis.material,
                    "pattern": updated_item.pattern if updated_item else analysis.pattern,
                    "fit": updated_item.fit if updated_item else analysis.fit,
                    "length": updated_item.length if updated_item else analysis.length,
                    "sleeve_length": updated_item.sleeve_length if updated_item else analysis.sleeve_length,
                    "neckline": updated_item.neckline if updated_item else analysis.neckline,
                    "layering_role": updated_item.layering_role if updated_item else analysis.layering_role,
                    "warmth_level": updated_item.warmth_level if updated_item else analysis.warmth_level,
                    "formality_score": updated_item.formality_score if updated_item else analysis.formality_score,
                    "analysis_version": analysis.analysis_version,
                    "taxonomy_version": analysis.taxonomy_version,
                    "semantic_model": settings.openai_embedding_model,
                },
            )
            self.repository.add_feature_snapshot(feature_snapshot)
            self.repository.complete_recognition_job(job.id)
            log_event(
                "recognition_job.complete",
                job_id=job.id,
                user_id=job.user_id,
                clothing_item_id=job.clothing_item_id,
                provider=analysis.source,
                confidence=analysis.confidence,
            )
        except Exception as error:
            log_event(
                "recognition_job.failed",
                job_id=job.id,
                user_id=job.user_id,
                clothing_item_id=job.clothing_item_id,
                attempts=job.attempts,
                error=str(error),
            )
            self.repository.fail_recognition_job(job.id, str(error), max_attempts=settings.recognition_worker_max_attempts)
            self.repository.update_item(
                job.clothing_item_id,
                {
                    "recognition_source": RecognitionSource.FAILED,
                    "recognition_summary": "Recognition failed after upload.",
                    "metadata": {"pipeline": PIPELINE_NAME, "recognition_status": RecognitionStatus.FAILED},
                },
            )

def feature_vector(analysis) -> list[float]:
    # Keep the DB vector at 13 dimensions while allowing richer product categories.
    category_group = CATEGORY_VECTOR_GROUPS.get(analysis.category, "Upper")
    return [
        1.0 if category_group == category else 0.0
        for category in CORE_CATEGORY_VECTOR_LABELS
    ] + [
        1.0 if analysis.style == style else 0.0
        for style in CORE_STYLE_VECTOR_LABELS
    ]
