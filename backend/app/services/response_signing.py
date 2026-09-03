from __future__ import annotations

from app.models.domain import ClothingItemRecord
from app.services.storage_service import StorageService


def absolute_url(base_url: str, url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("/"):
        return base_url.rstrip("/") + url
    return url


class ResponseSigningService:
    def __init__(self, storage_service: StorageService) -> None:
        self.storage_service = storage_service

    def item(self, item: ClothingItemRecord, base_url: str) -> ClothingItemRecord:
        signed_url = absolute_url(base_url, self.storage_service.signed_image_url(item.image_path))
        return self._signed_item(item, base_url, signed_url)

    def items(self, items: list[ClothingItemRecord], base_url: str) -> list[ClothingItemRecord]:
        signed_urls = self.storage_service.signed_image_urls([item.image_path for item in items])
        return [
            self._signed_item(item, base_url, absolute_url(base_url, signed_urls.get(item.image_path or "")))
            for item in items
        ]

    def recommendations(self, recommendations, base_url: str):
        all_items = [item for recommendation in recommendations for item in recommendation.items]
        signed_urls = self.storage_service.signed_image_urls([item.image_path for item in all_items])

        def signed_recommendation_items(items: list[ClothingItemRecord]) -> list[ClothingItemRecord]:
            return [
                self._signed_item(item, base_url, absolute_url(base_url, signed_urls.get(item.image_path or "")))
                for item in items
            ]

        return [
            recommendation.model_copy(update={"items": signed_recommendation_items(recommendation.items)})
            for recommendation in recommendations
        ]

    def preferences(self, preferences: dict, base_url: str) -> dict:
        payload = dict(preferences)
        memory = dict(payload.get("preferences") or {})
        profile = dict(memory.get("profile") or {})
        avatar_path = payload.get("avatar_path") or profile.get("avatar_path")
        if avatar_path:
            profile["avatar_path"] = avatar_path
            avatar_url = absolute_url(base_url, self.storage_service.signed_image_url(str(avatar_path)))
            if not avatar_url:
                avatar_url = absolute_url(base_url, self.storage_service.fallback_image_url(str(avatar_path)))
            profile["avatar_url"] = avatar_url
            payload["avatar_url"] = avatar_url
        memory["profile"] = profile
        payload["preferences"] = memory
        return payload

    def _signed_item(self, item: ClothingItemRecord, base_url: str, signed_url: str | None) -> ClothingItemRecord:
        fallback_url = self._item_fallback_url(item, base_url)
        return item.model_copy(update={"image_url": signed_url or fallback_url or item.image_url})

    def _item_fallback_url(self, item: ClothingItemRecord, base_url: str) -> str | None:
        local_fallback = self.storage_service.fallback_image_url(item.image_path)
        if local_fallback:
            return absolute_url(base_url, local_fallback)
        if item.image_url.startswith("http://") or item.image_url.startswith("https://"):
            return item.image_url
        if item.image_url.startswith("/"):
            return absolute_url(base_url, item.image_url)
        return None
