from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from app.core.constants import RECOGNITION_IN_PROGRESS_SOURCES, RETRYABLE_JOB_STATUSES, RecognitionStatus
from app.models.domain import ClothingItemRecord, ItemFeatureSnapshot, RecognitionJobRecord, RecognitionRecord, utc_now_iso
from app.services.preference_schema import default_preference_record, normalize_preference_record, normalize_preference_updates


class ClosetRepository:
    def __init__(self, items_path: Path | None = None) -> None:
        self.items_path = items_path or settings.items_path
        self.recognition_records_path = settings.recognition_records_path
        self.recognition_jobs_path = settings.recognition_jobs_path
        self.item_feature_snapshots_path = settings.item_feature_snapshots_path
        self.user_preferences_path = settings.data_dir / "user_preferences.json"
        self.items_path.parent.mkdir(parents=True, exist_ok=True)
        self.recognition_records_path.parent.mkdir(parents=True, exist_ok=True)
        self.recognition_jobs_path.parent.mkdir(parents=True, exist_ok=True)
        self.item_feature_snapshots_path.parent.mkdir(parents=True, exist_ok=True)
        self.user_preferences_path.parent.mkdir(parents=True, exist_ok=True)

    def list_items(self, user_id: str | None = None) -> list[ClothingItemRecord]:
        items = self._read_all()
        if user_id:
            items = [item for item in items if item.user_id == user_id]
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def list_items_for_recommendation(self, user_id: str | None = None) -> list[ClothingItemRecord]:
        return self.list_items(user_id)

    def add_item(self, item: ClothingItemRecord) -> ClothingItemRecord:
        items = self._read_all()
        items.append(item)
        self._write_all(items)
        return item

    def update_item(self, item_id: str, updates: dict, user_id: str | None = None) -> ClothingItemRecord | None:
        items = self._read_all()
        updated_item: ClothingItemRecord | None = None
        next_items: list[ClothingItemRecord] = []
        for item in items:
            if item.id == item_id and (user_id is None or item.user_id == user_id):
                payload = item.model_dump()
                payload.update(updates)
                updated_item = ClothingItemRecord.model_validate(payload)
                next_items.append(updated_item)
            else:
                next_items.append(item)
        self._write_all(next_items)
        return updated_item

    def delete_item(self, item_id: str, user_id: str | None = None) -> ClothingItemRecord | None:
        items = self._read_all()
        deleted_item: ClothingItemRecord | None = None
        next_items: list[ClothingItemRecord] = []
        for item in items:
            if item.id == item_id and (user_id is None or item.user_id == user_id):
                deleted_item = item
            else:
                next_items.append(item)
        if not deleted_item:
            return None

        self._write_all(next_items)
        self._delete_related_records(item_id, user_id)
        return deleted_item

    def add_item_bundle(
        self,
        item: ClothingItemRecord,
        recognition_record: RecognitionRecord,
        feature_snapshot: ItemFeatureSnapshot,
    ) -> ClothingItemRecord:
        self.add_item(item)
        recognition_records = self._read_json_records(self.recognition_records_path, RecognitionRecord)
        recognition_records.append(recognition_record)
        self._write_json_records(self.recognition_records_path, recognition_records)

        feature_snapshots = self._read_json_records(self.item_feature_snapshots_path, ItemFeatureSnapshot)
        feature_snapshots.append(feature_snapshot)
        self._write_json_records(self.item_feature_snapshots_path, feature_snapshots)
        return item

    def add_recognition_record(self, recognition_record: RecognitionRecord) -> RecognitionRecord:
        recognition_records = self._read_json_records(self.recognition_records_path, RecognitionRecord)
        recognition_records.append(recognition_record)
        self._write_json_records(self.recognition_records_path, recognition_records)
        return recognition_record

    def add_feature_snapshot(self, feature_snapshot: ItemFeatureSnapshot) -> ItemFeatureSnapshot:
        feature_snapshots = self._read_json_records(self.item_feature_snapshots_path, ItemFeatureSnapshot)
        feature_snapshots.append(feature_snapshot)
        self._write_json_records(self.item_feature_snapshots_path, feature_snapshots)
        return feature_snapshot

    def create_recognition_job(self, job: RecognitionJobRecord) -> RecognitionJobRecord:
        jobs = self._read_json_records(self.recognition_jobs_path, RecognitionJobRecord)
        jobs.append(job)
        self._write_json_records(self.recognition_jobs_path, jobs)
        return job

    def delete_recognition_jobs_for_item(self, item_id: str, user_id: str | None = None) -> None:
        jobs = self._read_json_records(self.recognition_jobs_path, RecognitionJobRecord)
        next_jobs = [
            job
            for job in jobs
            if not (
                job.clothing_item_id == item_id
                and (user_id is None or job.user_id == user_id)
            )
        ]
        self._write_json_records(self.recognition_jobs_path, next_jobs)

    def claim_recognition_jobs(self, batch_size: int, max_attempts: int) -> list[RecognitionJobRecord]:
        jobs = self._read_json_records(self.recognition_jobs_path, RecognitionJobRecord)
        now = datetime.now(timezone.utc)
        claimed: list[RecognitionJobRecord] = []
        next_jobs: list[RecognitionJobRecord] = []
        for job in jobs:
            job = self._expire_or_dead_letter_job(job, max_attempts, now)
            if (
                len(claimed) < batch_size
                and job.status in RETRYABLE_JOB_STATUSES
                and job.attempts < max_attempts
                and self._is_due(job, now)
            ):
                payload = job.model_dump()
                payload.update(
                    {
                        "status": RecognitionStatus.PROCESSING,
                        "attempts": job.attempts + 1,
                        "leased_at": utc_now_iso(),
                        "updated_at": utc_now_iso(),
                    }
                )
                claimed_job = RecognitionJobRecord.model_validate(payload)
                claimed.append(claimed_job)
                next_jobs.append(claimed_job)
            else:
                next_jobs.append(job)
        self._write_json_records(self.recognition_jobs_path, next_jobs)
        return claimed

    def complete_recognition_job(self, job_id: str) -> None:
        self._update_recognition_job(
            job_id,
            {"status": RecognitionStatus.COMPLETE, "last_error": None, "leased_at": None, "next_run_at": None, "dead_lettered_at": None},
        )

    def fail_recognition_job(self, job_id: str, error: str, max_attempts: int | None = None) -> None:
        self._update_recognition_job(job_id, {"last_error": error}, max_attempts=max_attempts)

    def get_item(self, item_id: str, user_id: str | None = None) -> ClothingItemRecord | None:
        for item in self._read_all():
            if item.id == item_id and (user_id is None or item.user_id == user_id):
                return item
        return None

    def summary(self, user_id: str | None = None) -> dict[str, object]:
        items = self.list_items(user_id)
        recognized_items = [item for item in items if item.recognition_source not in RECOGNITION_IN_PROGRESS_SOURCES]
        counts = Counter(item.category for item in recognized_items)
        return {
            "total_items": len(items),
            "category_counts": dict(counts),
            "recent_items": items[:5],
        }

    def queue_health(self, user_id: str | None = None) -> dict[str, object]:
        jobs = self._read_json_records(self.recognition_jobs_path, RecognitionJobRecord)
        if user_id:
            jobs = [job for job in jobs if job.user_id == user_id]
        counts = Counter(job.status for job in jobs)
        queued_jobs = [job for job in jobs if job.status in RETRYABLE_JOB_STATUSES]
        processing_jobs = [job for job in jobs if job.status == RecognitionStatus.PROCESSING]
        dead_letter_jobs = [job for job in jobs if job.status == RecognitionStatus.DEAD_LETTER]
        return {
            "total_jobs": len(jobs),
            "status_counts": dict(counts),
            "oldest_queued_at": min((job.created_at for job in queued_jobs), default=None),
            "processing_jobs": len(processing_jobs),
            "dead_letter_jobs": len(dead_letter_jobs),
            "recent_errors": [
                {"id": job.id, "filename": job.filename, "attempts": job.attempts, "last_error": job.last_error}
                for job in sorted(dead_letter_jobs + [job for job in jobs if job.status == RecognitionStatus.FAILED], key=lambda job: job.updated_at, reverse=True)[:5]
            ],
        }

    def get_preferences(self, user_id: str) -> dict:
        preferences = self._read_preferences()
        return normalize_preference_record(preferences.get(user_id, default_preference_record(user_id)))

    def upsert_preferences(self, user_id: str, updates: dict) -> dict:
        preferences = self._read_preferences()
        existing = self.get_preferences(user_id)
        payload = normalize_preference_updates(user_id, existing, updates)
        payload["updated_at"] = utc_now_iso()
        preferences[user_id] = payload
        self.user_preferences_path.write_text(json.dumps(preferences, indent=2), encoding="utf-8")
        return payload

    def _read_all(self) -> list[ClothingItemRecord]:
        if not self.items_path.exists():
            return []
        raw = json.loads(self.items_path.read_text(encoding="utf-8"))
        return [ClothingItemRecord.model_validate(item) for item in raw]

    def _write_all(self, items: list[ClothingItemRecord]) -> None:
        payload = [item.model_dump() for item in items]
        self.items_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _read_preferences(self) -> dict:
        if not self.user_preferences_path.exists():
            return {}
        return json.loads(self.user_preferences_path.read_text(encoding="utf-8"))

    def _read_json_records(self, path: Path, model_cls):
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [model_cls.model_validate(item) for item in raw]

    def _write_json_records(self, path: Path, records: list) -> None:
        payload = [record.model_dump() for record in records]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _delete_related_records(self, item_id: str, user_id: str | None = None) -> None:
        for path, model_cls in [
            (self.recognition_records_path, RecognitionRecord),
            (self.recognition_jobs_path, RecognitionJobRecord),
            (self.item_feature_snapshots_path, ItemFeatureSnapshot),
        ]:
            records = self._read_json_records(path, model_cls)
            filtered = [
                record
                for record in records
                if not (
                    record.clothing_item_id == item_id
                    and (user_id is None or record.user_id == user_id)
                )
            ]
            self._write_json_records(path, filtered)

    def _update_recognition_job(self, job_id: str, updates: dict, max_attempts: int | None = None) -> None:
        jobs = self._read_json_records(self.recognition_jobs_path, RecognitionJobRecord)
        next_jobs: list[RecognitionJobRecord] = []
        for job in jobs:
            if job.id == job_id:
                payload = job.model_dump()
                payload.update(updates)
                if "status" not in updates and "last_error" in updates:
                    if max_attempts is not None and job.attempts >= max_attempts:
                        payload["status"] = RecognitionStatus.DEAD_LETTER
                        payload["dead_lettered_at"] = utc_now_iso()
                        payload["next_run_at"] = None
                    else:
                        payload["status"] = RecognitionStatus.FAILED
                        payload["next_run_at"] = self._next_retry_at(job.attempts)
                payload["updated_at"] = utc_now_iso()
                next_jobs.append(RecognitionJobRecord.model_validate(payload))
            else:
                next_jobs.append(job)
        self._write_json_records(self.recognition_jobs_path, next_jobs)

    def _expire_or_dead_letter_job(
        self,
        job: RecognitionJobRecord,
        max_attempts: int,
        now: datetime,
    ) -> RecognitionJobRecord:
        if job.status == RecognitionStatus.FAILED and job.attempts >= max_attempts:
            payload = job.model_dump()
            payload.update({"status": RecognitionStatus.DEAD_LETTER, "dead_lettered_at": utc_now_iso(), "updated_at": utc_now_iso()})
            return RecognitionJobRecord.model_validate(payload)

        if job.status != RecognitionStatus.PROCESSING or not job.leased_at:
            return job

        leased_at = self._parse_datetime(job.leased_at)
        if not leased_at:
            return job
        timed_out_at = leased_at + timedelta(seconds=settings.recognition_worker_job_timeout_seconds)
        if timed_out_at > now:
            return job

        payload = job.model_dump()
        if job.attempts >= max_attempts:
            payload.update(
                {
                    "status": RecognitionStatus.DEAD_LETTER,
                    "last_error": "Recognition job timed out.",
                    "next_run_at": None,
                    "dead_lettered_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            )
        else:
            payload.update(
                {
                    "status": RecognitionStatus.FAILED,
                    "last_error": "Recognition job timed out.",
                    "next_run_at": self._next_retry_at(job.attempts),
                    "updated_at": utc_now_iso(),
                }
            )
        return RecognitionJobRecord.model_validate(payload)

    def _is_due(self, job: RecognitionJobRecord, now: datetime) -> bool:
        if not job.next_run_at:
            return True
        next_run_at = self._parse_datetime(job.next_run_at)
        return next_run_at is None or next_run_at <= now

    def _next_retry_at(self, attempts: int) -> str:
        retry_seconds = min(
            settings.recognition_worker_retry_max_seconds,
            settings.recognition_worker_retry_base_seconds * (2 ** max(0, attempts - 1)),
        )
        return (datetime.now(timezone.utc) + timedelta(seconds=retry_seconds)).isoformat()

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
