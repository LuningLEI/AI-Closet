from __future__ import annotations

from supabase import create_client

from app.core.config import settings


class AuthService:
    def __init__(self) -> None:
        supabase_key = settings.supabase_service_role_key or settings.supabase_key
        self.client = None
        if settings.supabase_url and supabase_key:
            self.client = create_client(str(settings.supabase_url), supabase_key)

    def user_id_from_token(self, token: str | None) -> str | None:
        if not token or not self.client:
            return None
        try:
            response = self.client.auth.get_user(token)
            user = getattr(response, "user", None)
            return getattr(user, "id", None)
        except Exception as error:
            print("SUPABASE AUTH TOKEN VERIFY FAILED:", error)
            return None
