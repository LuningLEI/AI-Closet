from __future__ import annotations

from app.core.config import settings
from app.repositories.base import ClosetRepositoryProtocol
from app.repositories.closet_repository import ClosetRepository
from app.repositories.supabase_closet_repository import SupabaseClosetRepository


def build_closet_repository() -> ClosetRepositoryProtocol:
    supabase_key = settings.supabase_service_role_key or settings.supabase_key
    if settings.supabase_url and supabase_key:
        return SupabaseClosetRepository()
    return ClosetRepository()
