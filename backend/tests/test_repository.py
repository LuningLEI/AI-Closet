from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.versions import PROFILE_VERSION, STYLE_PREFERENCE_VERSION, TAXONOMY_VERSION
from app.models.domain import ClothingItemRecord, ItemFeatureSnapshot, RecognitionJobRecord, RecognitionRecord
from app.repositories.closet_repository import ClosetRepository


def item(item_id: str, user_id: str, category: str = "Tops") -> ClothingItemRecord:
    return ClothingItemRecord(
        id=item_id,
        user_id=user_id,
        image_url=f"https://example.test/{item_id}.jpg",
        image_path=f"{user_id}/{item_id}.jpg",
        category=category,
        color="White",
        season="All-Season",
        style="Casual",
        occasion="Everyday",
        recognition_source="OpenAI Vision",
    )


def test_list_get_update_and_summary_are_scoped_by_user(repository: ClosetRepository) -> None:
    user_a = "00000000-0000-4000-8000-0000000000a1"
    user_b = "00000000-0000-4000-8000-0000000000b1"
    repository.add_item(item("item-a", user_a, "Tops"))
    repository.add_item(item("item-b", user_b, "Shoes"))

    assert [record.id for record in repository.list_items(user_a)] == ["item-a"]
    assert [record.id for record in repository.list_items(user_b)] == ["item-b"]
    assert repository.get_item("item-b", user_a) is None

    assert repository.update_item("item-b", {"color": "Black"}, user_a) is None
    updated = repository.update_item("item-a", {"color": "Blue"}, user_a)
    assert updated is not None
    assert updated.color == "Blue"

    summary = repository.summary(user_a)
    assert summary["total_items"] == 1
    assert summary["category_counts"] == {"Tops": 1}


def test_delete_item_is_scoped_and_removes_related_records(repository: ClosetRepository) -> None:
    user_a = "00000000-0000-4000-8000-0000000000a1"
    user_b = "00000000-0000-4000-8000-0000000000b1"
    repository.add_item(item("item-a", user_a, "Tops"))
    repository.add_item(item("item-b", user_b, "Tops"))
    repository.add_recognition_record(
        RecognitionRecord(
            id="record-a",
            user_id=user_a,
            clothing_item_id="item-a",
            provider="test",
            normalized_payload={"category": "Tops"},
        )
    )
    repository.add_recognition_record(
        RecognitionRecord(
            id="record-b",
            user_id=user_b,
            clothing_item_id="item-b",
            provider="test",
            normalized_payload={"category": "Tops"},
        )
    )
    repository.add_feature_snapshot(
        ItemFeatureSnapshot(
            id="feature-a",
            user_id=user_a,
            clothing_item_id="item-a",
            feature_vector=[0.0] * 13,
        )
    )
    repository.create_recognition_job(
        RecognitionJobRecord(
            id="job-a",
            user_id=user_a,
            clothing_item_id="item-a",
            filename="shirt.jpg",
            image_url="https://example.test/shirt.jpg",
            image_path=f"{user_a}/shirt.jpg",
        )
    )

    assert repository.delete_item("item-b", user_a) is None

    deleted = repository.delete_item("item-a", user_a)

    assert deleted is not None
    assert repository.get_item("item-a", user_a) is None
    assert [record.id for record in repository.list_items(user_b)] == ["item-b"]
    assert repository.queue_health(user_a)["total_jobs"] == 0


def test_preferences_save_and_load_are_scoped_by_user(repository: ClosetRepository) -> None:
    user_a = "00000000-0000-4000-8000-0000000000a1"
    user_b = "00000000-0000-4000-8000-0000000000b1"

    saved = repository.upsert_preferences(
        user_a,
        {
            "default_location_label": "San Jose, CA",
            "default_latitude": 37.3382,
            "default_longitude": -121.8863,
            "preferences": {
                "onboarding_completed": True,
                "profile": {
                    "nickname": "Luning",
                    "birth_year": 2005,
                    "gender_identity": "Woman",
                    "daily_occasions": ["Everyday", "Work"],
                    "style_preferences": ["Casual", "Elegant"],
                },
                "taxonomy": {
                    "selected_categories": ["Tops", "Dresses"],
                    "custom_categories": ["Vintage"],
                },
            },
        },
    )

    assert saved["user_id"] == user_a
    assert saved["profile_version"] == PROFILE_VERSION
    assert saved["taxonomy_version"] == TAXONOMY_VERSION
    assert saved["style_preference_version"] == STYLE_PREFERENCE_VERSION
    assert saved["onboarding_completed"] is True
    assert saved["nickname"] == "Luning"
    assert saved["birth_year"] == 2005
    assert saved["gender_identity"] == "Woman"
    assert saved["daily_occasions"] == ["Everyday", "Work"]
    assert saved["style_preferences"] == ["Casual", "Elegant"]
    assert saved["selected_categories"] == ["Tops", "Dresses"]
    assert saved["custom_categories"] == ["Vintage"]
    assert saved["profile_features"]["style_preferences"] == ["Casual", "Elegant"]
    assert repository.get_preferences(user_a)["default_location_label"] == "San Jose, CA"
    assert repository.get_preferences(user_a)["preferences"]["profile"]["nickname"] == "Luning"
    assert repository.get_preferences(user_a)["preferences"]["schema_versions"]["profile"] == PROFILE_VERSION
    assert repository.get_preferences(user_b)["default_location_label"] is None
    assert repository.get_preferences(user_b)["preferences"]["onboarding_completed"] is False


def test_upload_queue_claims_jobs_with_attempt_limits(repository: ClosetRepository) -> None:
    user_id = "00000000-0000-4000-8000-0000000000a1"
    repository.create_recognition_job(
        RecognitionJobRecord(
            id="job-1",
            user_id=user_id,
            clothing_item_id="item-1",
            filename="shirt.jpg",
            image_url="https://example.test/shirt.jpg",
            image_path=f"{user_id}/shirt.jpg",
        )
    )
    repository.create_recognition_job(
        RecognitionJobRecord(
            id="job-2",
            user_id=user_id,
            clothing_item_id="item-2",
            filename="dress.jpg",
            image_url="https://example.test/dress.jpg",
            image_path=f"{user_id}/dress.jpg",
            status="failed",
            attempts=3,
        )
    )

    claimed = repository.claim_recognition_jobs(batch_size=2, max_attempts=3)

    assert [job.id for job in claimed] == ["job-1"]
    assert claimed[0].status == "processing"
    assert claimed[0].attempts == 1
    assert repository.claim_recognition_jobs(batch_size=2, max_attempts=3) == []

    repository.complete_recognition_job("job-1")
    assert repository.claim_recognition_jobs(batch_size=2, max_attempts=3) == []


def test_upload_queue_respects_retry_backoff_and_dead_letters(repository: ClosetRepository) -> None:
    user_id = "00000000-0000-4000-8000-0000000000a1"
    future_retry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    expired_lease = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    repository.create_recognition_job(
        RecognitionJobRecord(
            id="job-backoff",
            user_id=user_id,
            clothing_item_id="item-backoff",
            filename="backoff.jpg",
            image_url="https://example.test/backoff.jpg",
            image_path=f"{user_id}/backoff.jpg",
            status="failed",
            attempts=1,
            next_run_at=future_retry,
        )
    )
    repository.create_recognition_job(
        RecognitionJobRecord(
            id="job-timeout",
            user_id=user_id,
            clothing_item_id="item-timeout",
            filename="timeout.jpg",
            image_url="https://example.test/timeout.jpg",
            image_path=f"{user_id}/timeout.jpg",
            status="processing",
            attempts=3,
            leased_at=expired_lease,
        )
    )

    assert repository.claim_recognition_jobs(batch_size=2, max_attempts=3) == []

    health = repository.queue_health(user_id)
    assert health["status_counts"]["failed"] == 1
    assert health["status_counts"]["dead_letter"] == 1
    assert health["dead_letter_jobs"] == 1
