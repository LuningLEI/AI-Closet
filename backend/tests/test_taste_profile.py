from datetime import datetime, timedelta, timezone

import pytest

from app.models.domain import ClothingItemRecord
from app.outfits.models import Proposal
from app.services.taste_profile import (decay_factor, exploration_quota_met,
    generation_taste_context, reduce_sources, TasteLearningConfig)


def snapshot(color="Black", style="Casual"):
    return {"items": [{"id": "one", "category": "Tops", "subtype": "T-shirt",
                       "color": color, "style": style, "occasion": "Everyday",
                       "season": ["Spring", "Summer"], "pattern": "Solid"}],
            "context": {"occasion": "Everyday"}, "outfit_vector": [1.0, 0.0]}


def test_reducer_is_deterministic_and_reason_scoped():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sources = [
        {"id": "2", "kind": "liked", "created_at": now.isoformat(), "feature_snapshot": snapshot()},
        {"id": "1", "kind": "disliked", "created_at": now.isoformat(),
         "feature_snapshot": snapshot("Pink", "Romantic"), "reason_codes": ["color_pattern"]},
    ]
    first = reduce_sources(sources, now=now)
    assert first == reduce_sources(list(reversed(sources)), now=now)
    assert first["feature_weights"]["color:pink"] < 0
    assert first["feature_weights"].get("style:romantic", 0) == 0


def test_unexplained_dislike_does_not_change_ranking_weights():
    result = reduce_sources([{"id": "1", "kind": "disliked", "created_at": "2026-01-01T00:00:00+00:00",
                              "feature_snapshot": snapshot(), "reason_codes": []}],
                            now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result["feature_weights"] == {}
    assert result["generation_memory"]["latent_dislike_clusters"] == []


def test_inferred_evidence_decays_to_floor():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert decay_factor(now, now) == 1
    assert decay_factor(now - timedelta(days=270), now) == pytest.approx(.5)
    assert decay_factor(now - timedelta(days=10_000), now) == pytest.approx(0, abs=1e-9)


def test_generation_context_enforces_one_of_eight_exploration_outfits():
    anchor = ClothingItemRecord(user_id="u", image_url="", category="Tops", subtype="T-shirt")
    known = ClothingItemRecord(user_id="u", image_url="", category="Bottoms", subtype="Jeans")
    novel = ClothingItemRecord(user_id="u", image_url="", category="Bottoms", subtype="Skirt")
    profile = {
        "feature_weights": {"subtype:jeans": .8},
        "feature_evidence": {"subtype:jeans": {"count": 3, "wear_count": 0}},
        "generation_memory": {"evidence_threshold_met": True, "preferred": ["subtype:jeans"],
                              "avoid": [], "exploration_rate": .10},
        "free_text_summary": {"summary": "Likes simple outfits"},
    }
    context = generation_taste_context(anchor, [anchor, known, novel], profile, 8)
    assert context["exploration_outfit_count"] == 1
    assert novel.id in context["exploration_candidate_ids"]
    assert context["free_text_summary"]["summary"] == "Likes simple outfits"
    assert exploration_quota_met([Proposal(item_ids=[anchor.id, novel.id], reason="new")], context)
    assert not exploration_quota_met([Proposal(item_ids=[anchor.id, known.id], reason="known")], context)


def test_explicit_simulation_parameters_do_not_change_default_reducer_behavior():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sources = [{"id": str(index), "kind": "liked", "created_at": now.isoformat(),
                "feature_snapshot": snapshot()} for index in range(2)]
    default = reduce_sources(sources, now=now)
    conservative = reduce_sources(sources, now=now,
                                  config=TasteLearningConfig(generation_evidence_threshold=3))
    assert default["generation_memory"]["evidence_threshold_met"]
    assert not conservative["generation_memory"]["evidence_threshold_met"]
    assert reduce_sources(sources, now=now) == default
