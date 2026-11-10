from tools.evaluation.outfit_pairwise_visual_shadow import _pairs, _prompt, parser, summarize
from tools.evaluation.recognition_shadow import write_json_atomic


def test_pair_builder_limits_each_review_to_two_images():
    assert _pairs(["a"]) == [["a"]]
    assert _pairs(["a", "b", "c"]) == [["a", "b"], ["a", "c"], ["b", "c"]]
    assert max(map(len, _pairs(["a", "b", "c"]))) == 2


def test_pair_prompt_calls_out_visible_style_conflicts():
    prompt = _prompt()
    assert "athletic performance T-shirt" in prompt
    assert "must not override a visible conflict" in prompt


def test_pairwise_cli_defaults_to_strict_json_schema():
    args = parser().parse_args([
        "run", "--suite-dir", "/tmp/suite", "--model", "model",
        "--base-url", "https://candidate.test/v1", "--protocol", "chat-completions",
        "--api-key-env", "KEY", "--input-rate", "0", "--cached-rate", "0",
        "--output-rate", "0",
    ])
    assert args.schema_mode == "json-schema"


def test_pairwise_summary_fails_outfit_when_one_pair_fails(tmp_path):
    passing = {
        name: {"verdict": "pass", "reason": "compatible"}
        for name in ("physical_fit", "style_silhouette", "color_pattern", "thermal_occasion")
    }
    failing = {**passing, "style_silhouette": {"verdict": "fail", "reason": "sporty versus elegant"}}
    write_json_atomic(tmp_path / "results" / "P1.json", {
        "pair_id": "P1", "status": "succeeded", "source": {"outfit_id": "O1"},
        "latency_seconds": 1, "usage": {}, "review": passing,
    })
    write_json_atomic(tmp_path / "results" / "P2.json", {
        "pair_id": "P2", "status": "succeeded", "source": {"outfit_id": "O1"},
        "latency_seconds": 1, "usage": {}, "review": failing,
    })
    summary = summarize(tmp_path)
    assert summary["outfit_verdict_counts"]["fail"] == 1
    assert summary["outfit_pass_rate"] == 0
    assert "human_aesthetic_1_5" in (tmp_path / "annotation.csv").read_text()
