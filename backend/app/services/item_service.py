from __future__ import annotations

import traceback
import httpx
from app.repositories.read_retry import DatabaseReadUnavailable
from app.services.label_confirmation import confirmation, LABEL_FIELDS
from app.services.season_support import normalize_seasons
from app.services.catalog_support import legacy_length

from fastapi import HTTPException
from fastapi import UploadFile

from app.services.occasion_support import effective_occasion, model_occasions, occasion_overrides, occasion_set
from app.services.taxonomy import OCCASIONS,merge_preferences,user_taxonomy
from app.services.occasion_thresholds import user_thresholds

from app.core.constants import DEFAULT_SEASON, RecognitionSource, RecognitionStatus
from app.core.versions import ITEM_FEATURE_VERSION, MANUAL_TAXONOMY_EDIT_VERSION
from app.models.api import ClothingItemUpdateRequest, ImageEditMetadata
from app.models.domain import ClothingAnalysis, WearingProfile, ColorTone, ClothingItemRecord, ItemEditEvent, RecognitionRecord
from app.repositories.base import ClosetRepositoryProtocol
from app.services.embedding_service import EmbeddingService, item_embedding_text
from app.services.embedding_retry import annotate_attempt
from app.services.recognition_pipeline import feature_vector


class ItemService:
    def __init__(self, repository: ClosetRepositoryProtocol, embedding_service: EmbeddingService, storage_service=None) -> None:
        self.repository = repository
        self.embedding_service = embedding_service
        self.storage_service = storage_service

    def confirm_labels(self, user_id, item_id, payload):
        # Persist exactly the displayed values, not a later background prediction.
        values = {key:getattr(payload,key) for key in LABEL_FIELDS if key in payload.model_fields_set}
        for _ in range(5):
            current = self.repository.get_item(item_id,user_id)
            if current is None: raise HTTPException(404, "Clothing item not found.")
            # Opening a card is not a manual correction of pending/failure placeholders.
            if (current.recognition_status not in {RecognitionStatus.COMPLETE, RecognitionStatus.MANUAL}
                    or current.recognition_source in {RecognitionSource.HEURISTIC_FALLBACK, RecognitionSource.FAILED}
                    or current.category == 'Uncategorized' or values.get('category') == 'Uncategorized'):
                return current
            confirmed_values = {key:values.get(key,getattr(current,key)) for key in LABEL_FIELDS}
            if 'length' not in values: confirmed_values['length'] = current.length or legacy_length(current.subtype)
            updates = {**confirmed_values, 'recognition_status':RecognitionStatus.MANUAL,
                       'metadata':{**(current.metadata or {}), 'manual_override':True,
                                   'label_confirmation':confirmation(confirmed_values)}}
            if any(getattr(current,k)!=v for k,v in values.items()):
                updates['semantic_vector'] = None
                analysis = self._manual_analysis(payload)
                updates['feature_vector'] = feature_vector(analysis)
            result = self.repository.commit_item_change(current,updates)
            if result is not None: return result
        raise HTTPException(409, "Item changed while confirming. Please retry.")

    def update_item(self, user_id: str, item_id: str, payload: ClothingItemUpdateRequest) -> ClothingItemRecord:
        if payload.edit_source == "ios_card_open":
            return self.confirm_labels(user_id,item_id,payload)
        existing_item = self.repository.get_item(item_id, user_id)
        if not existing_item:
            raise HTTPException(status_code=404, detail="Clothing item not found.")

        current_thresholds = user_thresholds(self.repository, user_id)
        preferences=merge_preferences(self.repository.get_preferences(user_id).get('preferences',{}))
        allowed_occasions=user_taxonomy(preferences)['occasions']
        threshold = (payload.occasion_thresholds_at_edit or
                     (dict.fromkeys(OCCASIONS, payload.occasion_threshold_at_edit)
                      if payload.occasion_threshold_at_edit is not None else current_thresholds))
        expected_before = effective_occasion(existing_item, threshold)
        before = payload.occasion_before if payload.occasion_before is not None else expected_before
        if occasion_set(before) != occasion_set(expected_before):
            raise HTTPException(status_code=409, detail="Occasion changed since this item was opened. Refresh and try again.")
        selected = occasion_set(payload.occasion)
        if selected - set(allowed_occasions):
            raise HTTPException(status_code=422, detail="Unknown occasion label.")
        added = selected - occasion_set(before)
        removed = occasion_set(before) - selected
        previous_overrides = occasion_overrides(existing_item,allowed_occasions)
        overrides = {
            "added": [label for label in allowed_occasions if label in (set(previous_overrides['added']) | added) - removed],
            "removed": [label for label in allowed_occasions if label in (set(previous_overrides['removed']) | removed) - added],
        }
        metadata = {**(existing_item.metadata or {}), "occasion_overrides": overrides}
        projected = existing_item.model_copy(update={"metadata": metadata})
        analysis = self._manual_analysis(payload)
        analysis.occasion = payload.occasion if (existing_item.metadata or {}).get("label_confirmation") else effective_occasion(projected, current_thresholds)
        previous_tags = existing_item.recognition_tags or {}
        analysis.wearing_profile = WearingProfile.model_validate(previous_tags.get("wearing_profile") or {})
        analysis.color_tones = [ColorTone.model_validate(t) for t in previous_tags.get('color_tones',[]) if t.get('color') in {v.strip() for v in analysis.color.split(',')}]
        analysis.occasion_scores = ClothingAnalysis.model_validate({
            "occasion_scores": previous_tags.get("occasion_scores", []),
        }).occasion_scores
        analysis.occasion_threshold = previous_tags.get("occasion_threshold")
        analysis.occasion_thresholds = previous_tags.get("occasion_thresholds", {})
        for field in ('material','length','sleeve_length'):
            value = getattr(payload,field) if field in payload.model_fields_set else getattr(existing_item,field)
            if field == 'length' and field not in payload.model_fields_set:
                value = value or legacy_length(existing_item.subtype)
            setattr(analysis,field,value)
        updates = {
            "length": analysis.length,
            "material": analysis.material,
            "sleeve_length": analysis.sleeve_length,
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
                **metadata,
                "recognition_status": RecognitionStatus.MANUAL,
                "manual_override": True,
            },
        }
        item_for_embedding = existing_item.model_copy(
            update={
                "material": analysis.material,
                "length": analysis.length,
                "sleeve_length": analysis.sleeve_length,
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
        updates["metadata"] = annotate_attempt(item_for_embedding, updates["metadata"], updates["semantic_vector"])
        updates["metadata"]["label_confirmation"] = confirmation(updates)
        updated_item = existing_item.model_copy(update=updates)

        changes = self._attribute_changes(existing_item, updated_item)
        # Occasion events describe user gestures relative to the UI snapshot, not stale DB labels.
        changes.pop("occasion", None)
        if added or removed:
            changes["occasion"] = {
                "before": before,
                "after": payload.occasion,
                "added": [label for label in allowed_occasions if label in added],
                "removed": [label for label in allowed_occasions if label in removed],
                "threshold_at_edit": next(iter(threshold.values())) if len(set(threshold.values())) == 1 else None,
                "thresholds_at_edit": threshold,
                "model_selected_at_edit": model_occasions(existing_item, threshold),
                "effective_after": updated_item.occasion,
            }
        event = ItemEditEvent(
                    user_id=user_id,
                    clothing_item_id=item_id,
                    event_type="item_attributes_updated",
                    source=payload.edit_source,
                    changed_fields=list(changes),
                    changes=changes,
                ) if changes else None

        recognition = RecognitionRecord(
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
        updated_item = self.repository.commit_item_change(existing_item,updates,recognition=recognition,event=event)
        if updated_item is None:
            raise HTTPException(409,"Item changed while saving. Refresh and retry.")
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
        image_edit_metadata: ImageEditMetadata | None = None,
    ) -> ClothingItemRecord:
        phase = "lookup"
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
            phase = "upload"
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
            # Photo transformations preserve labels/vectors and never enqueue recognition.
            phase = "commit"
            updated_item = None
            for _ in range(5):
                current = self.repository.get_item(item_id,user_id)
                if current is None: break
                updates = {
                    "image_url":image_url, "image_path":stored.get("image_path"),
                    "recognition_status":RecognitionStatus.MANUAL,
                    "metadata":{**(current.metadata or {}), "manual_override":True,
                        "label_confirmation":(current.metadata or {}).get("label_confirmation") or confirmation(current.model_dump()),
                        **({"last_image_edit":image_edit_metadata.model_dump()} if image_edit_metadata else {})},
                }
                image_changes = {"image_path":{"before":current.image_path,"after":stored.get("image_path")}}
                if image_edit_metadata:
                    image_changes["image_transform"]={"before":(current.metadata or {}).get("last_image_edit"),"after":image_edit_metadata.model_dump()}
                event=ItemEditEvent(user_id=user_id,clothing_item_id=item_id,event_type="image_replaced",
                    source="ios" if image_edit_metadata else "unknown",changed_fields=list(image_changes),changes=image_changes)
                try:
                    updated_item = self.repository.commit_item_change(current,updates,event=event)
                except httpx.TransportError:
                    # The transaction may have committed before its response was lost.
                    # Read back this request's unique object path; never replay the write.
                    saved = self.repository.get_item(item_id, user_id)
                    if saved is None or saved.image_path != stored.get("image_path"):
                        raise
                    updated_item = saved
                if updated_item is not None: break
            if updated_item is None and self.repository.get_item(item_id,user_id) is not None:
                raise HTTPException(409,"Item changed while saving photo. Please retry.")
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
        except (httpx.TransportError, DatabaseReadUnavailable) as error:
            print("[item_service.replace_item_image] connection_failed",
                  {"phase": phase, "error_type": type(error).__name__})
            detail = ("The connection was interrupted while saving the photo. Close and reopen the item to check whether it saved before trying again."
                      if phase == "commit" else
                      "The connection was interrupted before the photo could be saved. Please try Save again.")
            raise HTTPException(status_code=503, detail=detail) from error
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

    @staticmethod
    def _attribute_changes(before: ClothingItemRecord, after: ClothingItemRecord) -> dict[str, dict]:
        fields = LABEL_FIELDS
        return {
            field: {"before": getattr(before, field), "after": getattr(after, field)}
            for field in fields
            if getattr(before, field) != getattr(after, field)
            and (field != "season" or normalize_seasons(before.season) != normalize_seasons(after.season))
        }

    def _record_edit_event(self, event: ItemEditEvent) -> None:
        # Analytics must not turn a completed user save into a failed request.
        try:
            self.repository.add_item_edit_event(event)
        except Exception as error:
            print(
                "[item_service.edit_event_failed]",
                {"item_id": event.clothing_item_id, "event_type": event.event_type, "error": str(error)},
            )
