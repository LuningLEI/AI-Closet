from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories.closet_repository import ClosetRepository


@pytest.fixture
def repository(tmp_path: Path) -> ClosetRepository:
    repo = ClosetRepository(items_path=tmp_path / "items.json")
    repo.recognition_records_path = tmp_path / "recognition_records.json"
    repo.recognition_jobs_path = tmp_path / "recognition_jobs.json"
    repo.item_feature_snapshots_path = tmp_path / "item_feature_snapshots.json"
    repo.user_preferences_path = tmp_path / "user_preferences.json"
    return repo
