from __future__ import annotations

import csv
import json

import pytest

from tools.evaluation.baseline_eval import BaselineCandidate, BaselineLook, BaselineResult, DirectVisionBaseline, write_artifacts


def test_baseline_export_maps_model_codes_to_catalog_items(tmp_path) -> None:
    candidates = [
        BaselineCandidate("I001", "item-1", "White Shirt", "Tops", "White", "Casual", "Everyday", "https://example.com/1.jpg"),
        BaselineCandidate("I002", "item-2", "Blue Jeans", "Bottoms", "Blue", "Casual", "Everyday", "https://example.com/2.jpg"),
    ]
    result = BaselineResult(
        run_id="run-1",
        user_id="user-1",
        model="test-model",
        generated_at="2026-09-21T00:00:00+00:00",
        temperature_f=72,
        occasion="Everyday",
        style="Casual",
        requested_looks=1,
        candidate_count=2,
        latency_seconds=12.5,
        recommendation_summary="A simple daytime outfit.",
        looks=[BaselineLook(1, ["I001", "I002"], "Light layers for mild weather.")],
        usage={"input_tokens": 10, "output_tokens": 5},
    )

    write_artifacts(tmp_path, result, candidates, {"output_text": "{}"})

    with (tmp_path / "results.csv").open(newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert row["image_codes"] == "I001 | I002"
    assert row["item_ids"] == "item-1 | item-2"
    assert row["item_titles"] == "White Shirt | Blue Jeans"
    assert "Look 1" in (tmp_path / "report.html").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "raw_response.json").read_text(encoding="utf-8")) == {"output_text": "{}"}


def test_baseline_rejects_an_unknown_image_code() -> None:
    with pytest.raises(ValueError, match="unknown image codes"):
        DirectVisionBaseline._result_from_output(
            {"recommendation_summary": "", "looks": [{"look_number": 1, "image_codes": ["I999"], "styling_note": ""}]},
            user_id="user-1",
            model="test-model",
            temperature_f=72,
            occasion="Everyday",
            style="Any",
            requested_looks=1,
            candidate_count=1,
            latency_seconds=1,
            allowed_codes={"I001"},
            usage={},
        )
