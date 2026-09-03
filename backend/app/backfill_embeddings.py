from __future__ import annotations

from app.repositories.factory import build_closet_repository
from app.core.constants import RECOGNITION_EXCLUDED_SOURCES
from app.services.embedding_service import EmbeddingService, item_embedding_text


def main() -> None:
    repository = build_closet_repository()
    embedding_service = EmbeddingService()
    items = repository.list_items_for_recommendation()
    updated = 0
    skipped = 0

    for item in items:
        if item.recognition_source in RECOGNITION_EXCLUDED_SOURCES or item.semantic_vector:
            skipped += 1
            continue

        semantic_vector = embedding_service.create_embedding(item_embedding_text(item))
        if not semantic_vector:
            skipped += 1
            continue

        repository.update_item(item.id, {"semantic_vector": semantic_vector})
        updated += 1

    print(f"EMBEDDING BACKFILL: updated={updated}, skipped={skipped}")


if __name__ == "__main__":
    main()
