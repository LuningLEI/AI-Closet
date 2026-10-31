"""Persistence and deterministic projection for per-user taste profiles."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.services.taste_profile import (ALGORITHM_VERSION, DECAY_FLOOR, EXPLORATION_RATE,
                                        HALF_LIFE_DAYS, reduce_sources)


def _empty(uid: str) -> dict:
    return {
        "user_id": uid, "profile_version": 0, "algorithm_version": ALGORITHM_VERSION,
        "source_version": 0, "projected_version": 0, "feature_weights": {},
        "feature_evidence": {}, "positive_centroid": None, "negative_centroid": None,
        "generation_memory": {"preferred": [], "avoid": [], "evidence_threshold_met": False,
                              "exploration_rate": EXPLORATION_RATE, "latent_dislike_clusters": []},
        "new_free_text_count": 0, "summarized_free_text_count": 0,
        "free_text_summary": {}, "free_text_summary_updated_at": None, "learning_reset_at": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class TasteProfileService:
    def __init__(self, store):
        self.store = store
        if not hasattr(store, "client"):
            with store.db() as db:
                db.execute("create table if not exists user_taste_profiles (user_id text primary key,data text not null)")

    def get(self, uid: str) -> dict:
        if hasattr(self.store, "client"):
            rows = (self.store.client.table("user_taste_profiles").select("*")
                    .eq("user_id", uid).limit(1).execute().data or [])
            return rows[0] if rows else _empty(uid)
        with self.store.db() as db:
            row = db.execute("select data from user_taste_profiles where user_id=?", (uid,)).fetchone()
        return json.loads(row[0]) if row else _empty(uid)

    def mark_source(self, uid: str) -> None:
        """Mark local sources dirty; Supabase RPCs perform this atomically."""
        if hasattr(self.store, "client"):
            return
        profile = self.get(uid)
        profile["source_version"] += 1
        self._put(profile)

    def _sources(self, uid: str, profile: dict) -> list[dict]:
        reset_at = profile.get("learning_reset_at")
        def after_reset(row):
            return not reset_at or str(row.get("created_at") or row.get("worn_at") or "") > reset_at

        if hasattr(self.store, "client"):
            client = self.store.client
            feedback = client.table("outfit_feedback_events").select("*").eq("user_id", uid).execute().data or []
            personal = client.table("personal_outfits").select("*").eq("user_id", uid).execute().data or []
            wear = client.table("outfit_wear_events").select("*").eq("user_id", uid).execute().data or []
        else:
            def rows(table):
                with self.store.db() as db:
                    return [json.loads(row[0]) for row in db.execute(f"select data from {table} where user_id=?", (uid,))]
            feedback, personal, wear = rows("outfit_feedback_events"), rows("personal_outfits"), rows("outfit_wear_events")

        # Only the latest explicit state for an exact composition contributes.
        latest = {}
        for row in feedback:
            key = row.get("composition_signature")
            if after_reset(row) and (key not in latest or str(row.get("created_at", "")) >= str(latest[key].get("created_at", ""))):
                latest[key] = row
        sources = [{**row, "kind": row.get("action")} for row in latest.values()]
        sources += [{**row, "kind": "personal", "created_at": row.get("created_at")} for row in personal if after_reset(row)]
        sources += [{**row, "kind": "wear", "created_at": row.get("worn_at")} for row in wear if after_reset(row)]
        return [row for row in sources if row.get("feature_snapshot")]

    def feedback_notes(self, uid: str, profile: dict | None = None) -> list[dict]:
        profile = profile or self.get(uid)
        reset_at = profile.get("learning_reset_at")
        if hasattr(self.store, "client"):
            rows = (self.store.client.table("outfit_feedback_events").select(
                "id,action,reason_codes,note,context,created_at").eq("user_id", uid).execute().data or [])
        else:
            with self.store.db() as db:
                rows = [json.loads(row[0]) for row in db.execute(
                    "select data from outfit_feedback_events where user_id=?", (uid,))]
        return sorted([
            {key: row.get(key) for key in ("id", "action", "reason_codes", "note", "context", "created_at")}
            for row in rows if str(row.get("note") or "").strip()
            and (not reset_at or str(row.get("created_at") or "") > reset_at)
        ], key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")))

    def ensure_current(self, uid: str) -> dict:
        try:
            profile = self.get(uid)
            if (profile.get("projected_version", 0) < profile.get("source_version", 0)
                    or profile.get("algorithm_version") != ALGORITHM_VERSION):
                return self.reduce_user(uid)
            return profile
        except Exception:
            # Rolling deployment: recommendations and existing outfit jobs remain
            # available before migration 017 is applied; personalization stays off.
            return _empty(uid)

    def reduce_user(self, uid: str, _attempt: int = 0) -> dict:
        profile = self.get(uid)
        projection = reduce_sources(self._sources(uid, profile))
        projection["new_free_text_count"] = max(
            0, len(self.feedback_notes(uid, profile)) - int(profile.get("summarized_free_text_count") or 0))
        if hasattr(self.store, "client"):
            published = self.store.client.rpc("publish_taste_profile", {
                "p_user": uid, "p_source_version": profile.get("source_version", 0),
                "p_projection": projection,
            }).execute().data
            if published:
                return self.get(uid)
            if _attempt >= 2:
                return self.get(uid)
            return self.reduce_user(uid, _attempt + 1)
        profile.update(projection)
        profile["projected_version"] = profile.get("source_version", 0)
        profile["profile_version"] = profile.get("profile_version", 0) + 1
        profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._put(profile)
        return profile

    def pending_users(self) -> list[str]:
        if hasattr(self.store, "client"):
            rows = self.store.client.table("user_taste_profiles").select(
                "user_id,source_version,projected_version,algorithm_version").execute().data or []
            return [row["user_id"] for row in rows
                    if row["source_version"] > row["projected_version"]
                    or row.get("algorithm_version") != ALGORITHM_VERSION]
        with self.store.db() as db:
            rows = [json.loads(row[0]) for row in db.execute("select data from user_taste_profiles")]
        return [row["user_id"] for row in rows
                if row.get("source_version", 0) > row.get("projected_version", 0)
                or row.get("algorithm_version") != ALGORITHM_VERSION]

    def reset(self, uid: str) -> dict:
        if hasattr(self.store, "client"):
            return self.store.client.rpc("reset_taste_profile", {"p_user": uid}).execute().data
        previous = self.get(uid)
        profile = _empty(uid)
        profile.update(source_version=previous.get("source_version", 0),
                       projected_version=previous.get("source_version", 0),
                       profile_version=previous.get("profile_version", 0) + 1,
                       learning_reset_at=datetime.now(timezone.utc).isoformat())
        self._put(profile)
        return profile

    def _put(self, profile: dict) -> None:
        if hasattr(self.store, "client"):
            self.store.client.table("user_taste_profiles").upsert(profile, on_conflict="user_id").execute()
        else:
            with self.store.db() as db:
                db.execute("insert into user_taste_profiles values (?,?) on conflict(user_id) do update set data=excluded.data",
                           (profile["user_id"], json.dumps(profile)))

    @staticmethod
    def public(profile: dict) -> dict:
        memory = profile.get("generation_memory") or {}
        evidence = profile.get("feature_evidence") or {}
        return {
            "profile_version": profile.get("profile_version", 0),
            "algorithm_version": profile.get("algorithm_version", ALGORITHM_VERSION),
            "source_version": profile.get("source_version", 0),
            "projected_version": profile.get("projected_version", 0),
            "preferred_features": memory.get("preferred", []),
            "avoided_features": memory.get("avoid", []),
            "evidence_count": sum(int(value.get("count", 0)) for value in evidence.values()),
            "pending_free_text_count": profile.get("new_free_text_count", 0),
            "summarized_free_text_count": profile.get("summarized_free_text_count", 0),
            "free_text_summary": profile.get("free_text_summary") or None,
            "exploration_rate": memory.get("exploration_rate", EXPLORATION_RATE),
            "inferred_preference_half_life_days": int(HALF_LIFE_DAYS),
            "inferred_preference_floor": DECAY_FLOOR,
            "learning_reset_at": profile.get("learning_reset_at"),
            "updated_at": profile.get("updated_at"),
        }
