from __future__ import annotations

from fastapi import HTTPException, UploadFile

from app.repositories.base import ClosetRepositoryProtocol
from app.services.storage_service import StorageService


class ProfileService:
    def __init__(self, repository: ClosetRepositoryProtocol, storage_service: StorageService) -> None:
        self.repository = repository
        self.storage_service = storage_service

    async def upload_avatar(self, user_id: str, file: UploadFile) -> dict:
        if file.content_type and not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Avatar must be an image file.")

        stored = await self.storage_service.store_profile_avatar(file, user_id)
        existing = self.repository.get_preferences(user_id)
        memory = dict(existing.get("preferences") or {})
        profile = dict(memory.get("profile") or {})
        profile["avatar_path"] = stored["image_path"]
        memory["profile"] = profile
        return self.repository.upsert_preferences(
            user_id,
            {
                "avatar_path": stored["image_path"],
                "preferences": memory,
            },
        )
