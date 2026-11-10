"""Read-only smoke test for the configured production recognition provider."""
from __future__ import annotations

import argparse
import json
import traceback

from app.repositories.supabase_closet_repository import SupabaseClosetRepository
from app.services.recognition_service import ClothingRecognitionService
from app.services.storage_service import StorageService
from app.services.taxonomy import merge_preferences, user_categories, user_taxonomy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--item-id", required=True)
    args = parser.parse_args()

    try:
        repository = SupabaseClosetRepository()
        item = repository.get_item(args.item_id, args.user_id)
        if item is None:
            raise ValueError("item not found")
        preferences = merge_preferences(
            repository.get_preferences(args.user_id).get("preferences", {})
        )
        image_url = StorageService().signed_image_url(item.image_path, expires_in=900)
        analysis = ClothingRecognitionService().analyze(
            item.image_path.rsplit("/", 1)[-1],
            image_url=image_url,
            allowed_categories=user_categories(preferences),
            user_profile=preferences.get("profile", {}),
            allowed_taxonomy=user_taxonomy(preferences),
            max_visual_calls=2,
        )
        print(json.dumps({
            "status": "ok",
            "category": analysis.category,
            "subtype": analysis.subtype,
            "color": analysis.color,
            "season": analysis.seasons,
            "style": analysis.style,
            "provider_source": str(analysis.source),
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "type": type(exc).__name__,
            "message": str(exc)[:300],
            "trace": [
                {"file": frame.filename.rsplit("/", 3)[-1], "line": frame.lineno, "name": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-5:]
            ],
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
