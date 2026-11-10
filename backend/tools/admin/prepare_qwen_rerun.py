"""Clear one user's live Outfit projection after verifying a recovery snapshot.

Historical recognition/outfit/model-call/feedback rows and image objects are
never deleted. Existing Outfit jobs are made obsolete so a new generation key
can enqueue clean work after recognition completes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.repositories.factory import build_closet_repository


def verify_snapshot(path: Path, user_id: str) -> dict:
    manifest = json.loads((path / "baseline_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "complete" or manifest.get("user_id") != user_id:
        raise ValueError("Snapshot is incomplete or belongs to a different user")
    if (path / "INCOMPLETE").exists():
        raise ValueError("Snapshot still has an INCOMPLETE marker")
    for line in (path / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        actual = hashlib.sha256((path / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Snapshot checksum mismatch: {relative}")
    return manifest


def count(client, table: str, user_id: str) -> int:
    result = client.table(table).select("id", count="exact").eq("user_id", user_id).limit(1).execute()
    return int(result.count or 0)


def prepare(user_id: str, snapshot: Path, *, apply: bool) -> dict:
    manifest = verify_snapshot(snapshot.resolve(), user_id)
    repository = build_closet_repository()
    client = getattr(repository, "client", None)
    if client is None:
        raise RuntimeError("This maintenance command requires Supabase storage mode")
    recognition_processing = client.table("recognition_jobs").select("id").eq(
        "user_id", user_id).eq("status", "processing").execute().data or []
    outfit_processing = client.table("outfit_build_jobs").select("id").eq(
        "user_id", user_id).eq("status", "processing").execute().data or []
    if recognition_processing or outfit_processing:
        raise RuntimeError("Workers still own processing jobs; stop them before applying the reset")
    before = {
        "current_outfits": count(client, "current_outfits", user_id),
        "outfit_build_jobs": count(client, "outfit_build_jobs", user_id),
    }
    report = {
        "user_id": user_id, "snapshot_id": manifest["snapshot_id"],
        "snapshot": str(snapshot.resolve()), "apply": apply, "before": before,
    }
    if not apply:
        return report
    client.table("outfit_build_jobs").update({
        "status": "obsolete", "lease_token": None, "lease_until": None,
        "error": "Superseded by the approved Qwen model-migration rerun",
    }).eq("user_id", user_id).neq("status", "obsolete").execute()
    # Child layers and projection-source links use ON DELETE CASCADE.
    client.table("current_outfits").delete().eq("user_id", user_id).execute()
    client.table("outfit_refresh_requests").update({
        "projected_version": 0, "projection_key": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).execute()
    report["after"] = {
        "current_outfits": count(client, "current_outfits", user_id),
        "active_outfit_jobs": int((client.table("outfit_build_jobs").select(
            "id", count="exact").eq("user_id", user_id).in_(
                "status", ["queued", "processing", "failed"]
            ).limit(1).execute().count) or 0),
    }
    if report["after"] != {"current_outfits": 0, "active_outfit_jobs": 0}:
        raise RuntimeError("Projection/job reset did not reach the required empty state")
    output = snapshot / "qwen_rerun_reset.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, type=UUID)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(str(args.user_id), args.snapshot, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
