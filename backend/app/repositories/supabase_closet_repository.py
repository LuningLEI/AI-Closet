from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from supabase import create_client, ClientOptions

from app.core.config import settings
from app.core.constants import RECOGNITION_IN_PROGRESS_SOURCES, RETRYABLE_JOB_STATUSES, RecognitionStatus
from app.models.domain import ClothingItemRecord, ItemEditEvent, ItemFeatureSnapshot, RecognitionJobRecord, RecognitionRecord
from app.services.preference_schema import default_preference_record, normalize_preference_record, normalize_preference_updates


class SupabaseClosetRepository:
    FULL_ITEM_COLUMNS = "*"
    LIST_ITEM_COLUMNS = ",".join(
        [
            "id",
            "user_id",
            "image_url",
            "image_path",
            "analysis_version",
            "taxonomy_version",
            "feature_version",
            "recognition_status",
            "category",
            "subtype",
            "color",
            "season",
            "style",
            "occasion",
            "material",
            "pattern",
            "fit",
            "length",
            "sleeve_length",
            "neckline",
            "layering_role",
            "warmth_level",
            "formality_score",
            "recognition_source",
            "recognition_summary",
            "recognition_confidence",
            "recognition_tags",
            "metadata",
            "created_at",
        ]
    )

    def __init__(self) -> None:
        supabase_key = settings.supabase_service_role_key or settings.supabase_key
        if not settings.supabase_url or not supabase_key:
            raise RuntimeError("Supabase repository requires SUPABASE_URL and a key.")
        # Avoid multiplexed HTTP/2 connection failures on long-lived workers/API.
        # TLS certificate verification remains enabled.
        self.client = create_client(str(settings.supabase_url), supabase_key,
            options=ClientOptions(httpx_client=httpx.Client(http2=False, timeout=120)))
        self.table_name = "clothing_items"
        self.recognition_table_name = "recognition_records"
        self.item_edit_events_table_name = "item_edit_events"
        self.recognition_jobs_table_name = "recognition_jobs"
        self.feature_snapshot_table_name = "item_feature_snapshots"
        self.preferences_table_name = "user_preferences"

    def commit_item_change(self, expected, updates, recognition=None, event=None, feature=None, job=None):
        from app.repositories.item_transactions import expected_item
        values=dict(updates)
        for key in ('semantic_vector','feature_vector'):
            if key in values: values[key]=self._serialize_vector(values[key])
        snapshot=feature.model_dump() if feature else None
        if snapshot: snapshot['feature_vector']=self._serialize_vector(feature.feature_vector)
        result=self.client.rpc('commit_item_change',{
            'p_expected':expected_item(expected),'p_updates':values,
            'p_recognition':recognition.model_dump() if recognition else None,
            'p_event':event.model_dump() if event else None,'p_feature':snapshot,
            'p_job':job.model_dump() if job else None,
        }).execute().data
        return self._from_row(result) if result else None

    def list_items(self, user_id: str | None = None) -> list[ClothingItemRecord]:
        query = self.client.table(self.table_name).select(self.LIST_ITEM_COLUMNS)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.order("created_at", desc=True).execute()
        rows = response.data or []
        return [self._from_row(row) for row in rows]

    def _all_user_rows(self, table: str, user_id: str, columns: str = "*") -> list[dict]:
        rows: list[dict] = []
        # Explicit pagination avoids silently truncating a user's wardrobe at the API row cap.
        while True:
            page = (self.client.table(table).select(columns).eq("user_id", user_id)
                    .order("id").range(len(rows), len(rows) + 499).execute()).data or []
            if not page:
                return rows
            rows.extend(page)

    def list_items_for_recognition_reset(self, user_id: str) -> list[ClothingItemRecord]:
        return [self._from_row(row) for row in self._all_user_rows(self.table_name, user_id)]

    def list_items_for_outfits(self, user_id: str) -> list[ClothingItemRecord]:
        return [self._from_row(row) for row in self._all_user_rows(self.table_name, user_id, self.LIST_ITEM_COLUMNS)]

    def list_items_for_outfit_candidates(self, user_id: str) -> list[ClothingItemRecord]:
        return [self._from_row(row) for row in self._all_user_rows(self.table_name, user_id, self.FULL_ITEM_COLUMNS)]

    def update_item_if_current(self, expected, updates):
        from app.services.label_confirmation import COMPARE_FIELDS
        import json
        payload = dict(updates)
        for key in ('semantic_vector','feature_vector'):
            if key in payload: payload[key] = self._serialize_vector(payload[key])
        query = self.client.table(self.table_name).update(payload).eq('id',expected.id).eq('user_id',expected.user_id)
        for key in COMPARE_FIELDS:
            value = getattr(expected,key)
            if value is None: query = query.is_(key,'null')
            else: query = query.eq(key,json.dumps(value,separators=(',',':')) if key == 'metadata' else value)
        rows = query.execute().data or []
        return self._from_row(rows[0]) if rows else None

    def list_embedding_retry_candidates(self) -> list[ClothingItemRecord]:
        rows=[]
        for offset in range(0,1000000,200):
            batch=self.client.table(self.table_name).select(self.FULL_ITEM_COLUMNS).is_('semantic_vector','null').in_('recognition_status',['manual','complete']).order('id').range(offset,offset+199).execute().data or []
            rows.extend(batch)
            if len(batch)<200:break
        return [self._from_row(row) for row in rows]

    def update_embedding_if_current(self, expected, updates):
        from app.services.embedding_retry import FIELDS
        import json
        payload=dict(updates)
        if 'semantic_vector' in payload:payload['semantic_vector']=self._serialize_vector(payload['semantic_vector'])
        query=self.client.table(self.table_name).update(payload).eq('id',expected.id).eq('user_id',expected.user_id).is_('semantic_vector','null')
        query=query.is_('metadata','null') if expected.metadata is None else query.eq('metadata',json.dumps(expected.metadata,separators=(',',':')))
        for field in FIELDS:
            value=getattr(expected,field)
            query=query.is_(field,'null') if value is None else query.eq(field,value)
        rows=query.execute().data or []
        return self._from_row(rows[0]) if rows else None

    def list_recognition_jobs(self, user_id: str) -> list[RecognitionJobRecord]:
        return [RecognitionJobRecord.model_validate(row)
                for row in self._all_user_rows(self.recognition_jobs_table_name, user_id)]

    def list_items_for_recommendation(self, user_id: str | None = None) -> list[ClothingItemRecord]:
        query = self.client.table(self.table_name).select(self.FULL_ITEM_COLUMNS)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.order("created_at", desc=True).execute()
        rows = response.data or []
        return [self._from_row(row) for row in rows]

    def add_item(self, item: ClothingItemRecord) -> ClothingItemRecord:
        payload = item.model_dump()
        payload["feature_vector"] = self._serialize_vector(item.feature_vector)
        payload["semantic_vector"] = self._serialize_vector(item.semantic_vector)
        response = self.client.table(self.table_name).insert(payload).execute()
        row = (response.data or [payload])[0]
        return self._from_row(row)

    def update_item(self, item_id: str, updates: dict[str, Any], user_id: str | None = None) -> ClothingItemRecord | None:
        payload = dict(updates)
        if "feature_vector" in payload:
            payload["feature_vector"] = self._serialize_vector(payload["feature_vector"])
        if "semantic_vector" in payload:
            payload["semantic_vector"] = self._serialize_vector(payload["semantic_vector"])
        query = self.client.table(self.table_name).update(payload).eq("id", item_id)
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.execute()
        rows = response.data or []
        return self._from_row(rows[0]) if rows else self.get_item(item_id, user_id)

    def delete_item(self, item_id: str, user_id: str | None = None) -> ClothingItemRecord | None:
        existing_item = self.get_item(item_id, user_id)
        if not existing_item:
            return None
        query = self.client.table(self.table_name).delete().eq("id", item_id)
        if user_id:
            query = query.eq("user_id", user_id)
        query.execute()
        return existing_item

    def add_item_bundle(
        self,
        item: ClothingItemRecord,
        recognition_record: RecognitionRecord,
        feature_snapshot: ItemFeatureSnapshot,
    ) -> ClothingItemRecord:
        return self.create_item_with_records(item,recognition_record,feature_snapshot)

    def create_item_with_records(self,item,recognition=None,feature=None,job=None):
        payload=item.model_dump()
        for key in ('semantic_vector','feature_vector'):payload[key]=self._serialize_vector(payload[key])
        snapshot=feature.model_dump() if feature else None
        if snapshot:snapshot['feature_vector']=self._serialize_vector(feature.feature_vector)
        result=self.client.rpc('create_item_with_records',{'p_item':payload,
            'p_recognition':recognition.model_dump() if recognition else None,
            'p_feature':snapshot,'p_job':job.model_dump() if job else None}).execute().data
        return self._from_row(result)

    def add_recognition_record(self, recognition_record: RecognitionRecord) -> RecognitionRecord:
        self.client.table(self.recognition_table_name).insert(recognition_record.model_dump()).execute()
        return recognition_record

    def add_item_edit_event(self, event: ItemEditEvent) -> ItemEditEvent:
        self.client.table(self.item_edit_events_table_name).insert(event.model_dump()).execute()
        return event

    def add_feature_snapshot(self, feature_snapshot: ItemFeatureSnapshot) -> ItemFeatureSnapshot:
        payload = feature_snapshot.model_dump()
        payload["feature_vector"] = self._serialize_vector(feature_snapshot.feature_vector)
        self.client.table(self.feature_snapshot_table_name).insert(payload).execute()
        return feature_snapshot

    def create_recognition_job(self, job: RecognitionJobRecord) -> RecognitionJobRecord:
        response = self.client.table(self.recognition_jobs_table_name).insert(job.model_dump()).execute()
        row = (response.data or [job.model_dump()])[0]
        return RecognitionJobRecord.model_validate(row)

    def delete_recognition_jobs_for_item(self, item_id: str, user_id: str | None = None) -> None:
        query = self.client.table(self.recognition_jobs_table_name).delete().eq("clothing_item_id", item_id)
        if user_id:
            query = query.eq("user_id", user_id)
        query.execute()

    def claim_recognition_jobs(self, batch_size: int, max_attempts: int) -> list[RecognitionJobRecord]:
        response = self.client.rpc(
            "claim_recognition_jobs",
            {
                "batch_limit": batch_size,
                "max_attempts": max_attempts,
                "job_timeout_seconds": settings.recognition_worker_job_timeout_seconds,
            },
        ).execute()
        return [RecognitionJobRecord.model_validate(row) for row in response.data or []]

    def complete_recognition_job(self, job_id: str) -> None:
        self.client.table(self.recognition_jobs_table_name).update(
            {"status": RecognitionStatus.COMPLETE, "last_error": None, "leased_at": None, "next_run_at": None, "dead_lettered_at": None}
        ).eq("id", job_id).execute()

    def fail_recognition_job(self, job_id: str, error: str, max_attempts: int | None = None) -> None:
        attempts = 0
        response = self.client.table(self.recognition_jobs_table_name).select("attempts").eq("id", job_id).limit(1).execute()
        rows = response.data or []
        if rows:
            attempts = int(rows[0].get("attempts") or 0)
        dead_letter = max_attempts is not None and attempts >= max_attempts
        payload = {
            "status": RecognitionStatus.DEAD_LETTER if dead_letter else RecognitionStatus.FAILED,
            "last_error": error,
            "next_run_at": None if dead_letter else self._next_retry_at(attempts),
            "dead_lettered_at": datetime.now(timezone.utc).isoformat() if dead_letter else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.client.table(self.recognition_jobs_table_name).update(
            payload
        ).eq("id", job_id).execute()

    def get_item(self, item_id: str, user_id: str | None = None) -> ClothingItemRecord | None:
        from app.repositories.read_retry import execute_read
        def request():
            query = self.client.table(self.table_name).select("*").eq("id", item_id)
            if user_id:
                query = query.eq("user_id", user_id)
            return query.limit(1)
        response = execute_read(request)
        rows = response.data or []
        return self._from_row(rows[0]) if rows else None

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
        query = self.client.table(self.recognition_jobs_table_name).select("*")
        if user_id:
            query = query.eq("user_id", user_id)
        response = query.order("updated_at", desc=True).execute()
        jobs = [RecognitionJobRecord.model_validate(row) for row in response.data or []]
        counts = Counter(job.status for job in jobs)
        queued_jobs = [job for job in jobs if job.status in RETRYABLE_JOB_STATUSES]
        dead_letter_jobs = [job for job in jobs if job.status == RecognitionStatus.DEAD_LETTER]
        return {
            "total_jobs": len(jobs),
            "status_counts": dict(counts),
            "oldest_queued_at": min((job.created_at for job in queued_jobs), default=None),
            "processing_jobs": counts.get(RecognitionStatus.PROCESSING, 0),
            "dead_letter_jobs": counts.get(RecognitionStatus.DEAD_LETTER, 0),
            "recent_errors": [
                {"id": job.id, "filename": job.filename, "attempts": job.attempts, "last_error": job.last_error}
                for job in dead_letter_jobs + [job for job in jobs if job.status == RecognitionStatus.FAILED]
                if job.last_error
            ][:5],
        }

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        response = self.client.table(self.preferences_table_name).select("*").eq("user_id", user_id).limit(1).execute()
        rows = response.data or []
        if rows:
            return normalize_preference_record(rows[0])
        return default_preference_record(user_id)

    def upsert_preferences(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_preferences(user_id)
        payload = normalize_preference_updates(user_id, existing, updates)
        # API-only projection; the durable value lives in preferences.taxonomy
        # so this feature requires no schema column or migration.
        payload.pop("taxonomy_customizations", None)
        payload.pop("occasion_style_preferences", None)
        for field in (
            "personalization_enabled",
            "feedback_learning_enabled",
            "exploration_level",
            "rotation_level",
            "temperature_sensitivity",
        ):
            payload.pop(field, None)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = self.client.table(self.preferences_table_name).upsert(payload, on_conflict="user_id").execute()
        rows = response.data or [payload]
        return normalize_preference_record(rows[0])

    def _from_row(self, row: dict[str, Any]) -> ClothingItemRecord:
        payload = dict(row)
        payload["feature_vector"] = self._deserialize_vector(payload.get("feature_vector"))
        payload["semantic_vector"] = self._deserialize_vector(payload.get("semantic_vector"))
        return ClothingItemRecord.model_validate(payload)

    def _serialize_vector(self, value: list[float] | None) -> str | None:
        if value is None:
            return None
        return "[" + ",".join(f"{component:.6f}" for component in value) + "]"

    def _deserialize_vector(self, value: Any) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(component) for component in value]
        if isinstance(value, str):
            stripped = value.strip().strip("[]")
            if not stripped:
                return []
            return [float(component) for component in stripped.split(",")]
        return None

    def _next_retry_at(self, attempts: int) -> str:
        retry_seconds = min(
            settings.recognition_worker_retry_max_seconds,
            settings.recognition_worker_retry_base_seconds * (2 ** max(0, attempts - 1)),
        )
        return (datetime.now(timezone.utc) + timedelta(seconds=retry_seconds)).isoformat()
