from __future__ import annotations

from typing import Any, Protocol

from app.models.domain import ClothingItemRecord, ItemFeatureSnapshot, RecognitionJobRecord, RecognitionRecord


class ClosetRepositoryProtocol(Protocol):
    def list_items(self, user_id: str | None = None) -> list[ClothingItemRecord]:
        ...

    def list_items_for_recommendation(self, user_id: str | None = None) -> list[ClothingItemRecord]:
        ...

    def add_item(self, item: ClothingItemRecord) -> ClothingItemRecord:
        ...

    def update_item(self, item_id: str, updates: dict[str, Any], user_id: str | None = None) -> ClothingItemRecord | None:
        ...

    def delete_item(self, item_id: str, user_id: str | None = None) -> ClothingItemRecord | None:
        ...

    def add_item_bundle(
        self,
        item: ClothingItemRecord,
        recognition_record: RecognitionRecord,
        feature_snapshot: ItemFeatureSnapshot,
    ) -> ClothingItemRecord:
        ...

    def add_recognition_record(self, recognition_record: RecognitionRecord) -> RecognitionRecord:
        ...

    def add_feature_snapshot(self, feature_snapshot: ItemFeatureSnapshot) -> ItemFeatureSnapshot:
        ...

    def create_recognition_job(self, job: RecognitionJobRecord) -> RecognitionJobRecord:
        ...

    def delete_recognition_jobs_for_item(self, item_id: str, user_id: str | None = None) -> None:
        ...

    def claim_recognition_jobs(self, batch_size: int, max_attempts: int) -> list[RecognitionJobRecord]:
        ...

    def complete_recognition_job(self, job_id: str) -> None:
        ...

    def fail_recognition_job(self, job_id: str, error: str, max_attempts: int | None = None) -> None:
        ...

    def get_item(self, item_id: str, user_id: str | None = None) -> ClothingItemRecord | None:
        ...

    def summary(self, user_id: str | None = None) -> dict[str, object]:
        ...

    def queue_health(self, user_id: str | None = None) -> dict[str, object]:
        ...

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        ...

    def upsert_preferences(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        ...
