"""Export a read-only outerwear candidate distribution for the current closet."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from app.core.constants import DEFAULT_USER_ID
from app.outfits.config import load_config
from app.outfits.outerwear_distribution import (
    SHADOW_POLICY_VERSION,
    OuterwearShadowConfig,
    outerwear_distribution,
    upper_inner_items,
)
from app.outfits.service import OutfitLibrary, ready
from app.outfits.store import build_store
from app.repositories.factory import build_closet_repository
from app.services.taste_profile_service import TasteProfileService
from tools.evaluation.paths import evaluation_path


class IdentitySigner:
    def items(self, items, base_url):
        return items


def _user_with_most_items(repository) -> str:
    if hasattr(repository, "client"):
        counts: Counter[str] = Counter()
        offset = 0
        while True:
            batch = (repository.client.table(repository.table_name).select("user_id")
                     .range(offset, offset + 499).execute().data or [])
            counts.update(str(row["user_id"]) for row in batch)
            if len(batch) < 500:
                break
            offset += len(batch)
        if not counts:
            raise ValueError("No clothing items are available")
        return counts.most_common(1)[0][0]
    return DEFAULT_USER_ID


def _library_outfits(library: OutfitLibrary, user_id: str):
    outfits = []
    offset = 0
    while True:
        page = library.list(user_id, IdentitySigner(), "", offset=offset, limit=100)
        outfits.extend(page.outfits)
        if page.next_offset is None:
            return outfits
        offset = page.next_offset


def export_distribution(
    user_id: str | None,
    output_dir: Path,
    *,
    temperature_f: float,
    occasion: str,
    softmax_temperature: float,
) -> tuple[Path, Path]:
    repository = build_closet_repository()
    selected_user = user_id or _user_with_most_items(repository)
    store = build_store(repository)
    outfit_config = load_config()
    library = OutfitLibrary(repository, store, outfit_config)
    items = [item for item in repository.list_items_for_outfit_candidates(selected_user) if ready(item)]
    outerwear = [item for item in items if item.category == "Outerwear" or item.subtype in {"Cardigan", "Athletic Jacket", "Ski Jacket"}]
    outfits = _library_outfits(library, selected_user)
    try:
        taste = TasteProfileService(store).get(selected_user)
    except Exception:
        taste = {}
    shadow_config = OuterwearShadowConfig(
        softmax_temperature=softmax_temperature,
        temperature_f=temperature_f,
        occasion=occasion,
    )

    rows = []
    skipped_without_upper = 0
    for outfit in outfits:
        base = [item for item in outfit.items if item.category != "Outerwear" and item.subtype not in {"Cardigan", "Athletic Jacket", "Ski Jacket"}]
        inners = upper_inner_items(base)
        if not inners:
            skipped_without_upper += 1
            continue
        current_outerwear = {
            item.id
            for variant in outfit.optional_additions
            for item in variant.items
            if item.category == "Outerwear" or item.subtype in {"Cardigan", "Athletic Jacket", "Ski Jacket"}
        }
        distribution = outerwear_distribution(
            base,
            outerwear,
            config=shadow_config,
            taste_profile=taste,
            compatibility_rules=outfit_config.compatibility_rules,
            seed=f"{selected_user}:{outfit.id}:{SHADOW_POLICY_VERSION}",
        )
        item_by_id = {item.id: item for item in outerwear}
        base_ids = [item.id for item in base]
        inner_ids = [item.id for item in inners]
        for candidate in distribution:
            garment = item_by_id.get(candidate.outerwear_id)
            rows.append({
                **candidate.row(),
                "shadow_policy_version": SHADOW_POLICY_VERSION,
                "source_outfit_id": outfit.id,
                "base_item_ids": " | ".join(base_ids),
                "inner_item_ids": " | ".join(inner_ids),
                "inner_titles": " | ".join(item.subtype or item.category for item in inners),
                "outerwear_id": candidate.outerwear_id or "NONE",
                "outerwear_title": "No outerwear" if garment is None else garment.subtype or garment.category,
                "outerwear_fit": "" if garment is None else garment.fit or "",
                "outerwear_material": "" if garment is None else garment.material or "",
                "production_present": bool(candidate.outerwear_id and candidate.outerwear_id in current_outerwear),
            })

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "outerwear_candidate_distribution.csv"
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    groups = {row["source_outfit_id"] for row in rows}
    selected = [row for row in rows if row["shadow_selected"]]
    masked = [row for row in rows if row["masked"]]
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_user_id": selected_user,
        "production_writes": False,
        "model_calls": 0,
        "shadow_only": True,
        "policy_version": SHADOW_POLICY_VERSION,
        "config": {
            "temperature_f": temperature_f,
            "occasion": occasion,
            "softmax_temperature": softmax_temperature,
        },
        "counts": {
            "ready_items": len(items),
            "outerwear_candidates": len(outerwear),
            "library_outfits": len(outfits),
            "evaluated_base_outfits": len(groups),
            "skipped_without_upper": skipped_without_upper,
            "candidate_rows": len(rows),
            "masked_rows": len(masked),
            "shadow_selections": len(selected),
            "shadow_selected_none": sum(row["outerwear_id"] == "NONE" for row in selected),
        },
        "interpretation": (
            "These are uncalibrated shadow-v1 probabilities from explicit heuristic scores. "
            "They are for inspection and human-label calibration, not production selection."
        ),
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", help="User UUID. Defaults to the closet owner with the most items.")
    parser.add_argument("--temperature-f", type=float, default=60.0)
    parser.add_argument("--occasion", default="Everyday")
    parser.add_argument("--softmax-temperature", type=float, default=0.75)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=evaluation_path("outfits", "outerwear_shadow", datetime.now().strftime("%Y%m%d-%H%M%S")),
    )
    args = parser.parse_args()
    csv_path, manifest_path = export_distribution(
        args.user_id,
        args.output_dir,
        temperature_f=args.temperature_f,
        occasion=args.occasion,
        softmax_temperature=args.softmax_temperature,
    )
    print(csv_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
