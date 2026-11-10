from tools.evaluation.outfit_model_shadow import (
    _balanced_anchors,
    _bottom_evaluation_catalog,
    _estimated_cost,
    _gateway,
    _generation_prompt,
    _parse_proposals_with_repairs,
    _validate_proposals,
    derive_metadata_only_suite,
    summarize,
)
from app.models.domain import ClothingItemRecord
from app.outfits.config import load_config
from app.outfits.models import Proposal, Proposals
from tools.evaluation.recognition_shadow import write_json_atomic


class Item:
    def __init__(self, identifier, category):
        self.id = identifier
        self.category = category


def test_outfit_suite_balances_anchor_categories():
    items = [Item("t2", "Tops"), Item("t1", "Tops"), Item("b1", "Bottoms"), Item("o1", "Outerwear")]
    assert [item.category for item in _balanced_anchors(items, 3)] == ["Bottoms", "Outerwear", "Tops"]


def test_outfit_cost_uses_cached_rate():
    usage = {"input_tokens": 1000, "cached_input_tokens": 250, "output_tokens": 100}
    assert _estimated_cost(usage, {"input": 1, "cached_input": 0.5, "output": 2}) == 0.001075


def test_outfit_shadow_gateway_rejects_non_strict_schema_mode():
    try:
        _gateway(
            "chat-completions", base_url="https://candidate.test/v1",
            api_key="secret", schema_mode="json-object",
        )
    except ValueError as error:
        assert "strict JSON Schema" in str(error)
    else:
        raise AssertionError("non-strict outfit shadow calls must be rejected")


def test_metadata_only_prompt_explicitly_removes_image_assumption():
    prompt = _generation_prompt("Inspect supplied images.", "metadata-only")
    assert "No garment images are supplied" in prompt
    assert "Never claim to have visually inspected" in prompt
    image_prompt = _generation_prompt("base", "metadata-and-images")
    assert image_prompt.startswith("base")
    assert "at most two layered proposals" in image_prompt


def _item(category, subtype, identifier, **kwargs):
    return ClothingItemRecord(
        id=identifier, user_id="user", image_url="", category=category,
        subtype=subtype, **kwargs,
    )


def test_bottom_shadow_catalog_caps_tops_and_prioritizes_activewear():
    anchor = _item("Activewear", "Workout Leggings", "anchor")
    active_tops = [
        _item("Activewear", "Workout Top", f"active-{index}")
        for index in range(3)
    ]
    general_tops = [
        _item("Tops", "T-shirt", f"top-{index}")
        for index in range(20)
    ]
    outerwear = [
        _item("Outerwear", "Jacket", f"outer-{index}")
        for index in range(12)
    ]
    selected = _bottom_evaluation_catalog(
        anchor, [anchor, *general_tops, *outerwear, *active_tops],
        load_config(), None, 30,
    )
    selected_tops = [item for item in selected if item.category in {"Tops", "Activewear"}
                     and item.subtype not in {"Workout Leggings"}]
    assert selected[0].id == "anchor"
    assert {item.id for item in selected[1:4]} == {item.id for item in active_tops}
    assert len(selected_tops) == 12
    assert sum(item.category == "Outerwear" for item in selected) == 8
    assert len(selected) == 21  # Underfill instead of adding more than 15 Tops.


def test_bottom_shadow_validation_limits_optional_top_layers():
    anchor = _item("Bottoms", "Trousers", "anchor")
    catalog = [anchor]
    proposals = []
    for index in range(3):
        base = _item("Tops", "T-shirt", f"base-{index}")
        layer = _item("Tops", "Hoodie", f"layer-{index}")
        catalog.extend([base, layer])
        proposals.append(Proposal(
            item_ids=[anchor.id, base.id, layer.id], reason="layered",
        ))
    rows = _validate_proposals(
        Proposals(outfits=proposals),
        scenario={"anchor_item_id": anchor.id}, catalog=catalog,
        config=load_config(),
    )
    assert rows[0]["valid"] is True
    assert rows[1]["valid"] is True
    assert rows[2]["valid"] is False
    assert "optional_layer_quota_exceeded" in rows[2]["rejection_codes"]


def test_outfit_parser_audits_equivalent_items_field_repair():
    proposals, actions, raw_valid = _parse_proposals_with_repairs(
        '{"outfits":[{"items":["a","b"],"reason":"coherent"}],"total_outfits":1}',
    )
    assert proposals.outfits[0].item_ids == ["a", "b"]
    assert actions == ["drop_redundant_total_outfits", "rename_items_to_item_ids"]
    assert raw_valid is False


def test_outfit_parser_repairs_object_ids_and_slot_shape_without_inference():
    proposals, actions, raw_valid = _parse_proposals_with_repairs(
        '{"maximum_outfits":2,"outfits":['
        '{"items":[{"id":"a"},{"id":"b"}],"reason":"paired"},'
        '{"top":"c","bottom":"d","accessories":["e"],"items":3}'
        ']}',
    )
    assert [row.item_ids for row in proposals.outfits] == [["a", "b"], ["c", "d", "e"]]
    assert proposals.outfits[1].reason == ""
    assert actions == [
        "drop_top_level_field:maximum_outfits",
        "extract_item_ids_from_objects",
        "reshape_slot_fields_to_item_ids",
    ]
    assert raw_valid is False


def test_outfit_summary_reports_hard_rule_yield_and_writes_annotation(tmp_path):
    write_json_atomic(tmp_path / "results" / "S001.json", {
        "scenario_id": "S001", "status": "succeeded", "latency_seconds": 2,
        "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5},
        "estimated_cost_usd": 0.01,
        "proposals": [
            {"item_ids": ["a", "b"], "valid": True, "rejection_codes": []},
            {"item_ids": ["a"], "valid": False, "rejection_codes": ["missing_bottom"]},
        ],
    })
    summary = summarize(tmp_path)
    assert summary["scenario_success_rate"] == 1
    assert summary["hard_rule_valid_rate"] == 0.5
    assert summary["mean_valid_proposals_per_scenario"] == 1
    rows = (tmp_path / "annotation.csv").read_text()
    assert "physically_wearable_1_5" in rows
    assert "missing_bottom" in rows


def test_derived_metadata_suite_preserves_frozen_inputs(monkeypatch, tmp_path):
    source = tmp_path / "source"
    write_json_atomic(source / "items.json", {"a": {"id": "a"}})
    write_json_atomic(source / "scenarios.json", [{"scenario_id": "S001"}])
    write_json_atomic(source / "output_schema.json", {"type": "object"})
    from tools.evaluation.recognition_shadow import digest

    write_json_atomic(source / "suite_manifest.json", {
        "suite_id": "source", "items_sha256": digest({"a": {"id": "a"}}),
        "scenarios_sha256": digest([{"scenario_id": "S001"}]),
    })
    monkeypatch.setattr(
        "tools.evaluation.outfit_model_shadow.load_config",
        lambda: type("Config", (), {"clothing_text": "Inspect images."})(),
    )
    derived = derive_metadata_only_suite(source_suite=source, output_root=tmp_path / "out")
    manifest = __import__("json").loads((derived / "suite_manifest.json").read_text())
    assert manifest["derived_from_suite"] == "source"
    assert manifest["input_mode"] == "metadata-only"
    assert "No garment images are supplied" in (derived / "prompt.txt").read_text()
