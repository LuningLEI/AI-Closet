import json

from app.outfits.models import CurrentVisualReview
from tools.evaluation.outfit_visual_shadow import _parse_review, _visual_prompt, summarize
from tools.evaluation.recognition_shadow import write_json_atomic


def review_payload():
    criterion = {"verdict": "pass", "reason": "compatible"}
    checks = {
        "wearability": criterion,
        "thermal": criterion,
        "color_pattern": criterion,
        "occasion": criterion,
    }
    return {
        "core": checks,
        "full": checks,
        "optional_layering": {"verdict": "not_applicable", "reason": "none"},
    }


def test_visual_parser_can_unwrap_equivalent_review_envelope():
    parsed, actions, raw_valid = _parse_review(json.dumps({"review": review_payload()}))
    assert isinstance(parsed, CurrentVisualReview)
    assert actions == ["unwrap_review"]
    assert raw_valid is False


def test_visual_prompt_forbids_bare_verdict_strings():
    prompt = _visual_prompt("base")
    assert "Never use a bare string" in prompt
    assert "optional_layering MUST be an object" in prompt


def test_visual_summary_reports_criterion_counts(tmp_path):
    write_json_atomic(tmp_path / "results" / "V001.json", {
        "review_id": "V001",
        "status": "succeeded",
        "source": {"source_model": "generator", "item_ids": ["a", "b"]},
        "latency_seconds": 2.0,
        "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5},
        "estimated_cost_usd": 0.01,
        "review": review_payload(),
    })
    summary = summarize(tmp_path)
    assert summary["review_success_rate"] == 1
    assert summary["core_all_pass_rate"] == 1
    assert summary["criterion_counts"]["core"]["wearability"]["pass"] == 1
    assert "human_looks_compatible_1_5" in (tmp_path / "annotation.csv").read_text()
