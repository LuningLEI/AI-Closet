"""Read-only smoke test for the production Qwen outfit provider.

Loads current wardrobe rows, but never creates jobs or writes database state.
Only a compact, non-sensitive JSON summary is printed.
"""
from __future__ import annotations

import argparse
import json
import traceback

from app.outfits.config import load_config
from app.outfits.diagnostics import error_details
from app.outfits.footwear import (
    _accessories_for,
    _prepared_candidates,
    clothing_catalog,
    footwear_catalog,
)
from app.outfits.provider import VisionOutfitProvider
from app.repositories.supabase_closet_repository import SupabaseClosetRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--anchor-id", required=True)
    args = parser.parse_args()

    phase = "load"
    try:
        config = load_config()
        repository = SupabaseClosetRepository()
        items = repository.list_items_for_outfit_candidates(args.user_id)
        by_id = {item.id: item for item in items}
        anchor = by_id[args.anchor_id]
        provider = VisionOutfitProvider(config)

        phase = "generation"
        catalog = clothing_catalog(anchor, items, config)
        proposals, generation_usage = provider.generate_clothing(anchor, catalog)
        stats = {"invalid": 0, "candidate_diagnostics": []}
        prepared = _prepared_candidates(anchor, catalog, proposals, config, stats)
        if not prepared:
            print(json.dumps({
                "status": "error",
                "phase": "generation_validation",
                "generated_count": len(proposals.outfits),
                "structurally_valid_count": 0,
                "diagnostics": stats["candidate_diagnostics"],
            }, sort_keys=True))
            return 1

        phase = "accessory_selection"
        selected_inputs = []
        for entry in prepared[:2]:
            clothing = entry["clothing"]
            selected_inputs.append((
                entry["candidate_index"],
                clothing,
                footwear_catalog(clothing, items, config, anchor=anchor),
                _accessories_for(clothing, anchor, items, config),
            ))
        selections, selection_usage = provider.select_accessories_batch(selected_inputs)

        phase = "visual_review"
        review_inputs = []
        for candidate_index, clothing, shoes, accessories in selected_inputs:
            selection = next(
                row for row in selections.selections
                if row.candidate_index == candidate_index
            )
            members = list(clothing)
            members.extend(shoe for shoe in shoes if shoe.id == selection.selected_shoe_id)
            members.extend(
                accessory for accessory in accessories
                if accessory.id in set(selection.accessory_ids)
            )
            review_inputs.append((candidate_index, members))
        reviews, review_usage = provider.evaluate_batch(review_inputs)

        print(json.dumps({
            "status": "ok",
            "catalog_count": len(catalog),
            "generated_count": len(proposals.outfits),
            "structurally_valid_count": len(prepared),
            "selection_count": len(selections.selections),
            "review_count": len(reviews.reviews),
            "review_pass_count": sum(
                row.review.core.passes() and row.review.full.passes()
                for row in reviews.reviews
            ),
            "usage_present": {
                "generation": generation_usage is not None,
                "selection": selection_usage is not None,
                "review": review_usage is not None,
            },
        }, sort_keys=True))
        return 0
    except Exception as exc:
        details = error_details(exc, phase=phase)
        print(json.dumps({
            "status": "error",
            "phase": phase,
            "type": type(exc).__name__,
            "message": str(exc)[:300],
            "trace": [
                {"file": frame.filename.rsplit("/", 3)[-1], "line": frame.lineno, "name": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-5:]
            ],
            "details": details,
            "provider_message": getattr(exc, "provider_message", None),
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
