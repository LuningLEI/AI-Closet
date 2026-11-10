"""Export a read-only, integrity-checked baseline before changing AI providers.

The export contains complete rows for one user, including vectors and audit
history. It never writes to Supabase and refuses to overwrite an existing
snapshot directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from postgrest.exceptions import APIError
from supabase import ClientOptions, create_client

from app.core.config import settings
from app.core.runtime_snapshot import runtime_config_snapshot
from app.outfits.config import load_config


REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "evaluation" / "model_migration" / "baselines"


@dataclass(frozen=True)
class TableSpec:
    name: str
    order: tuple[str, ...]
    required: bool = False
    user_scoped: bool = True


TABLES = (
    TableSpec("clothing_items", ("id",), True),
    TableSpec("recognition_records", ("id",), True),
    TableSpec("recognition_jobs", ("id",)),
    TableSpec("item_edit_events", ("id",)),
    TableSpec("item_feature_snapshots", ("id",), True),
    TableSpec("user_preferences", ("user_id",), True),
    TableSpec("outfit_libraries", ("user_id",)),
    TableSpec("outfit_build_jobs", ("id",)),
    TableSpec("outfits", ("id",), True),
    TableSpec("outfit_items", ("outfit_id", "clothing_item_id"), True),
    TableSpec("outfit_refresh_requests", ("user_id",)),
    TableSpec("current_outfits", ("id",)),
    TableSpec("current_outfit_layers", ("outfit_id", "id")),
    TableSpec("outfit_runs", ("id",)),
    TableSpec("outfit_model_calls", ("id",)),
    TableSpec("outfit_run_results", ("run_id", "outfit_id")),
    TableSpec("outfit_projection_sources", ("current_outfit_id", "evaluation_id")),
    TableSpec("history_maintenance_runs", ("id",)),
    TableSpec("personal_outfits", ("id",)),
    TableSpec("outfit_wear_events", ("id",)),
    TableSpec("outfit_daily_selections", ("wear_date",)),
    TableSpec("outfit_feedback_events", ("id",)),
    TableSpec("user_outfit_feedback_state", ("composition_signature",)),
    TableSpec("user_taste_profiles", ("user_id",), True),
    TableSpec("taste_summary_runs", ("id",)),
    TableSpec("data_retention_policies", ("dataset",), user_scoped=False),
)

RESTORE_ORDER = [
    "clothing_items", "recognition_records", "recognition_jobs", "item_edit_events",
    "item_feature_snapshots", "user_preferences", "outfit_libraries", "outfit_runs",
    "outfit_build_jobs", "outfits", "outfit_items", "current_outfits",
    "current_outfit_layers", "outfit_run_results", "outfit_projection_sources",
    "outfit_refresh_requests", "outfit_model_calls", "history_maintenance_runs",
    "personal_outfits", "outfit_wear_events", "outfit_daily_selections",
    "outfit_feedback_events", "user_outfit_feedback_state", "user_taste_profiles",
    "taste_summary_runs",
]

CONFIG_FILES = (
    "backend/app/core/versions.py",
    "backend/app/outfits/config.json",
    "backend/app/outfits/prompts/evaluate.txt",
    "backend/app/outfits/prompts/generate.txt",
    "backend/app/outfits/prompts/generate_clothing.txt",
    "backend/app/outfits/prompts/review_visual.txt",
    "backend/app/outfits/prompts/select_accessories.txt",
    "backend/app/outfits/prompts/select_footwear.txt",
    "backend/app/services/taste_profile.py",
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n", encoding="utf-8")


def safe_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def git_identity() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(args, cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()

    return {
        "commit": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "branch", "--show-current"),
        "dirty": bool(run("git", "status", "--porcelain")),
    }


def fetch_rows(client: Any, spec: TableSpec, user_id: str, page_size: int = 500) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while True:
        query = client.table(spec.name).select("*")
        if spec.user_scoped:
            query = query.eq("user_id", user_id)
        for column in spec.order:
            query = query.order(column)
        page = query.range(len(rows), len(rows) + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            break
    return rows


def reference_checks(tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(child: str, field: str, parent: str, parent_field: str = "id") -> None:
        parent_values = {str(row.get(parent_field)) for row in tables.get(parent, [])}
        values = {str(row.get(field)) for row in tables.get(child, []) if row.get(field) is not None}
        missing = sorted(values - parent_values)
        checks.append({
            "relationship": f"{child}.{field} -> {parent}.{parent_field}",
            "status": "pass" if not missing else "warning",
            "missing_count": len(missing),
            "missing_sample": missing[:10],
        })

    check("recognition_records", "clothing_item_id", "clothing_items")
    check("recognition_jobs", "clothing_item_id", "clothing_items")
    check("item_edit_events", "clothing_item_id", "clothing_items")
    check("item_feature_snapshots", "clothing_item_id", "clothing_items")
    check("outfit_items", "outfit_id", "outfits")
    check("outfit_items", "clothing_item_id", "clothing_items")
    check("current_outfit_layers", "outfit_id", "current_outfits")
    check("outfit_projection_sources", "current_outfit_id", "current_outfits")
    check("outfit_projection_sources", "evaluation_id", "outfits")
    check("outfit_model_calls", "run_id", "outfit_runs")
    check("outfit_run_results", "run_id", "outfit_runs")
    check("outfit_run_results", "outfit_id", "outfits")
    check("outfit_daily_selections", "wear_event_id", "outfit_wear_events")
    return checks


def file_checksums(root: Path) -> list[dict[str, Any]]:
    values = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "CHECKSUMS.sha256"):
        data = path.read_bytes()
        values.append({"path": str(path.relative_to(root)), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    return values


def export(user_id: str, output_root: Path) -> Path:
    if not settings.supabase_url or not (settings.supabase_service_role_key or settings.supabase_key):
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY are required")

    started = datetime.now(timezone.utc)
    snapshot_id = f"{started.strftime('%Y%m%dT%H%M%SZ')}-{user_id}"
    target = output_root.resolve() / snapshot_id
    target.mkdir(parents=True, exist_ok=False)
    (target / "INCOMPLETE").write_text("Export in progress. Do not use for restore.\n", encoding="utf-8")

    client = create_client(
        str(settings.supabase_url),
        settings.supabase_service_role_key or settings.supabase_key,
        options=ClientOptions(httpx_client=httpx.Client(http2=False, timeout=120)),
    )
    tables: dict[str, list[dict[str, Any]]] = {}
    unavailable: dict[str, str] = {}
    for spec in TABLES:
        try:
            rows = fetch_rows(client, spec, user_id)
        except APIError as error:
            if spec.required:
                raise RuntimeError(f"Required table {spec.name} could not be exported: {error}") from error
            unavailable[spec.name] = str(error)
            continue
        tables[spec.name] = rows
        write_json(target / "tables" / f"{spec.name}.json", rows)

    # A second complete read detects concurrent changes without pausing workers.
    consistency: dict[str, Any] = {}
    for spec in TABLES:
        if spec.name not in tables:
            continue
        second = fetch_rows(client, spec, user_id)
        first_hash, second_hash = content_hash(tables[spec.name]), content_hash(second)
        consistency[spec.name] = {
            "stable": first_hash == second_hash,
            "row_count": len(tables[spec.name]),
            "content_sha256": first_hash,
        }

    items = tables.get("clothing_items", [])
    storage_paths = [
        {"item_id": row.get("id"), "image_path": row.get("image_path"), "image_url": row.get("image_url")}
        for row in items
    ]
    write_json(target / "storage_paths.json", storage_paths)

    outfit_config = load_config()
    runtime = runtime_config_snapshot(outfit_config).model_dump()
    runtime["models"] = {
        "recognition": settings.openai_vision_model,
        "recognition_image_detail": settings.openai_vision_detail,
        "embedding": settings.openai_embedding_model,
        "embedding_dimensions": settings.openai_embedding_dimensions,
        "agent_planner": settings.openai_agent_planner_model,
        "outfit_generation": outfit_config.generation_model,
        "outfit_evaluation": outfit_config.evaluation_model,
    }
    runtime["endpoints"] = {"ai_base_url": safe_url(settings.ai_base_url)}
    runtime["storage"] = {"bucket": settings.supabase_storage_bucket}
    write_json(target / "configuration" / "runtime.json", runtime)
    for relative in CONFIG_FILES:
        source = REPO_ROOT / relative
        if source.exists():
            destination = target / "configuration" / "source" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    checks = reference_checks(tables)
    stable = all(value["stable"] for value in consistency.values())
    verification = {
        "status": "pass" if stable and all(c["status"] == "pass" for c in checks) else "warning",
        "two_read_consistency": stable,
        "relationships": checks,
    }
    write_json(target / "verification.json", verification)

    manifest = {
        "schema_version": "model-migration-baseline-v1",
        "snapshot_id": snapshot_id,
        "user_id": user_id,
        "created_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if stable else "inconsistent",
        "read_only_export": True,
        "auth_user_exported": False,
        "auth_restore_precondition": f"auth.users must already contain {user_id}",
        "git": git_identity(),
        "tables": consistency,
        "unavailable_optional_tables": unavailable,
        "restore_order": RESTORE_ORDER,
        "storage_object_count": len(storage_paths),
        "notes": [
            "Vectors are preserved exactly as returned by PostgREST.",
            "Image objects were not downloaded; stable storage paths and URLs are recorded.",
            "Restore is intentionally not automatic: stop workers, validate in staging, then restore in one transaction.",
        ],
    }
    write_json(target / "baseline_manifest.json", manifest)
    (target / "RESTORE_README.md").write_text(
        "# Restore contract\n\n"
        "This snapshot is a complete user-scoped export, not an executable migration. Before restore:\n\n"
        f"1. Confirm `auth.users.id = {user_id}` exists.\n"
        "2. Stop API mutations and all workers.\n"
        "3. Verify `CHECKSUMS.sha256` and restore into staging first.\n"
        "4. Upsert tables in `baseline_manifest.json.restore_order` inside one database transaction.\n"
        "5. Rebuild/verify the current Outfit projection, then compare all row counts and hashes.\n\n"
        "Never restore over production without an explicit destructive-change approval.\n",
        encoding="utf-8",
    )

    # The temporary marker must not enter the immutable checksum index.
    (target / "INCOMPLETE").unlink()
    checksums = file_checksums(target)
    write_json(target / "artifact_index.json", checksums)
    checksum_lines = [f"{entry['sha256']}  {entry['path']}" for entry in file_checksums(target)]
    (target / "CHECKSUMS.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")
    if not stable:
        raise RuntimeError(f"Concurrent changes detected; snapshot retained but marked inconsistent: {target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    target = export(args.user_id, args.output_root)
    manifest = json.loads((target / "baseline_manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "status": manifest["status"],
        "snapshot": str(target),
        "user_id": args.user_id,
        "row_counts": {name: value["row_count"] for name, value in manifest["tables"].items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
