import json
from io import BytesIO
from types import SimpleNamespace

import httpx
from PIL import Image

from app.models.domain import ClothingItemRecord
from tools.evaluation.recognition_shadow import (
    ShadowEndpoint,
    ShadowHTTPError,
    _balanced,
    clone_run,
    _clean_response_text,
    _coerce_prediction_scalars,
    _estimated_usage_cost,
    _repair_candidate_text,
    _schema_prediction_with_local_repairs,
    _usage,
    _manual_reference,
    _redact_url,
    _resized_image_input,
    digest,
    prepare_run,
    reparse_results,
    safe_endpoint,
    summarize_run,
    write_json_atomic,
)


class ReadOnlyRepository:
    def __init__(self, items):
        self.items = items

    def list_items(self, user_id):
        return [item for item in self.items if item.user_id == user_id]

    def get_preferences(self, user_id):
        return {"user_id": user_id, "preferences": {}}


def test_prepare_freezes_references_without_model_or_database_write(tmp_path):
    item = ClothingItemRecord(
        id="item-1", user_id="user-1", image_url="private-path", image_path="user-1/item.jpg",
        recognition_status="manual", category="Tops", subtype="T-shirt", color="Blue",
        metadata={"label_confirmation": {"labels": {"category": "Tops", "subtype": "T-shirt"}}},
    )
    run_dir = prepare_run(
        user_id="user-1", model="candidate/model", base_url="https://candidate.test/v1",
        protocol="chat-completions", detail="low", limit=10, output_root=tmp_path,
        baseline="baseline-1", response_format="json-schema", image_max_dimension=448,
        output_max_tokens=512,
        repository=ReadOnlyRepository([item]),
    )
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    references = json.loads((run_dir / "references.json").read_text())
    assert manifest["state"] == "prepared"
    assert manifest["safety"]["production_writes"] is False
    assert manifest["reference"]["manual_confirmation_count"] == 1
    assert references[0]["image_path"] == "user-1/item.jpg"
    assert "image_url" not in references[0]
    assert manifest["candidate"]["image_preprocessing"] == {
        "max_dimension": 448, "mode": "fit-within", "format": "JPEG", "quality": 90,
    }
    assert manifest["candidate"]["output_max_tokens"] == 512
    assert manifest["candidate"]["response_format"] == "json-schema"
    assert (run_dir / "output_schema.json").exists()


def test_clone_reuses_byte_identical_frozen_inputs(tmp_path):
    item = ClothingItemRecord(
        id="item-1", user_id="user-1", image_url="private-path", image_path="user-1/item.jpg",
        recognition_status="manual", category="Tops", subtype="T-shirt", color="Blue",
    )
    source = prepare_run(
        user_id="user-1", model="baseline", base_url="https://baseline.test/v1",
        protocol="responses", detail="low", limit=1, output_root=tmp_path,
        baseline=None, response_format="json-schema", repository=ReadOnlyRepository([item]),
    )
    clone = clone_run(
        source_run=source, model="Qwen/test", base_url="https://router.test/v1",
        protocol="chat-completions", response_format="json-schema", output_root=tmp_path,
        image_max_dimension=448,
    )
    for name in ("prompt.txt", "references.json", "taxonomy.json", "output_schema.json"):
        assert (clone / name).read_bytes() == (source / name).read_bytes()
    manifest = json.loads((clone / "run_manifest.json").read_text())
    assert manifest["reference"]["cloned_from_run"] == source.name
    assert manifest["candidate"]["model"] == "Qwen/test"
    assert manifest["candidate"]["response_format"] == "json-schema"
    assert manifest["candidate"]["image_preprocessing"]["max_dimension"] == 448


def test_clone_can_append_versioned_prompt_variant(tmp_path):
    item = ClothingItemRecord(
        id="item-1", user_id="user-1", image_url="private-path",
        image_path="user-1/item.jpg", category="Tops", subtype="T-shirt",
    )
    source = prepare_run(
        user_id="user-1", model="baseline", base_url="https://baseline.test/v1",
        protocol="responses", detail="low", limit=1, output_root=tmp_path,
        baseline=None, response_format="json-schema", repository=ReadOnlyRepository([item]),
    )
    source_prompt = (source / "prompt.txt").read_text()
    clone = clone_run(
        source_run=source, model="Qwen/test", base_url="https://router.test/v1",
        protocol="chat-completions", response_format="json-schema", output_root=tmp_path,
        prompt_suffix="Mandatory consistency pass.", prompt_variant="qwen-layering-v2",
    )
    manifest = json.loads((clone / "run_manifest.json").read_text())
    assert (clone / "prompt.txt").read_text().startswith(source_prompt)
    assert (clone / "prompt.txt").read_text().endswith("Mandatory consistency pass.\n")
    assert manifest["candidate"]["prompt_variant"] == "qwen-layering-v2"
    assert manifest["reference"]["source_prompt_sha256"] != manifest["reference"]["prompt_sha256"]


def test_safe_endpoint_removes_credentials_query_and_fragment():
    assert safe_endpoint("https://example.test/v1/?token=no#part") == "https://example.test/v1"


def test_safe_endpoint_rejects_embedded_credentials():
    try:
        safe_endpoint("https://user:secret@example.test/v1")
    except ValueError:
        pass
    else:
        raise AssertionError("embedded credentials must be rejected")


def test_balanced_sample_round_robins_categories():
    items = [
        SimpleNamespace(id="3", category="Tops"), SimpleNamespace(id="1", category="Tops"),
        SimpleNamespace(id="2", category="Shoes"), SimpleNamespace(id="4", category="Bottoms"),
    ]
    assert [item.category for item in _balanced(items, 3)] == ["Bottoms", "Shoes", "Tops"]


def test_manual_reference_uses_only_confirmed_labels():
    item = SimpleNamespace(metadata={"label_confirmation": {"labels": {"category": "Tops", "subtype": "T-shirt", "other": 1}}})
    assert _manual_reference(item) == {"category": "Tops", "subtype": "T-shirt"}


def test_chat_endpoint_never_persists_or_returns_request_image_url():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"category":"Tops"}'}}], "usage": {}})

    endpoint = ShadowEndpoint(
        base_url="https://candidate.test/v1", api_key="secret", protocol="chat-completions",
        timeout=10, response_format="json-schema",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    payload, text = endpoint.request(
        model="vision", prompt="classify", image_url="https://signed.test/private",
        detail="low", max_tokens=512, schema={"type": "object"},
    )
    assert text == '{"category":"Tops"}'
    assert payload["choices"]
    assert seen["max_tokens"] == 512
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["response_format"]["json_schema"]["strict"] is True
    assert seen["messages"][0]["content"][1]["image_url"]["url"] == "https://signed.test/private"


def test_recognition_preparation_rejects_non_strict_output(tmp_path):
    item = ClothingItemRecord(
        id="item-1", user_id="user-1", image_url="private-path",
        image_path="user-1/item.jpg", category="Tops", subtype="T-shirt",
    )
    try:
        prepare_run(
            user_id="user-1", model="candidate/model",
            base_url="https://candidate.test/v1", protocol="chat-completions",
            detail="low", limit=1, output_root=tmp_path, baseline=None,
            response_format="json-object", repository=ReadOnlyRepository([item]),
        )
    except ValueError as error:
        assert "strict JSON Schema" in str(error)
    else:
        raise AssertionError("non-strict recognition runs must be rejected")


def test_responses_endpoint_sends_frozen_json_schema():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"output_text": "{}", "usage": {}})

    endpoint = ShadowEndpoint(
        base_url="https://candidate.test/v1", api_key="secret", protocol="responses",
        timeout=10, response_format="json-schema",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    endpoint.request(
        model="vision", prompt="classify", image_url="https://signed.test/private",
        detail="low", schema={"type": "object"},
    )
    assert seen["text"]["format"]["type"] == "json_schema"
    assert seen["text"]["format"]["strict"] is True


def test_gemini_endpoint_sends_inline_image_and_native_schema():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-goog-api-key")
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"text": '{"category":"Tops"}' }]}}],
            "usageMetadata": {
                "promptTokenCount": 300,
                "candidatesTokenCount": 20,
                "thoughtsTokenCount": 5,
            },
        })

    endpoint = ShadowEndpoint(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="gemini-secret", protocol="gemini-generate-content",
        timeout=10, response_format="json-schema",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    payload, text = endpoint.request(
        model="gemini-2.5-flash", prompt="classify",
        image_url="data:image/jpeg;base64,YWJj", detail="auto",
        max_tokens=512, schema={"type": "object"},
    )
    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent")
    assert seen["api_key"] == "gemini-secret"
    assert seen["authorization"] is None
    assert seen["body"]["contents"][0]["parts"][1] == {
        "inlineData": {"mimeType": "image/jpeg", "data": "YWJj"},
    }
    assert seen["body"]["generationConfig"] == {
        "temperature": 0,
        "responseMimeType": "application/json",
        "responseJsonSchema": {"type": "object"},
        "maxOutputTokens": 512,
    }
    assert text == '{"category":"Tops"}'
    assert _usage(payload) == {
        "input_tokens": 300,
        "cached_input_tokens": None,
        "output_tokens": 25,
        "reasoning_tokens": 5,
    }


def test_http_error_preserves_payload_and_classifies_local_oom():
    def handler(_request: httpx.Request):
        return httpx.Response(500, json={"detail": "Generation failed: Insufficient Memory"})

    endpoint = ShadowEndpoint(
        base_url="http://127.0.0.1:8081/v1", api_key=None, protocol="chat-completions",
        timeout=10, client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    try:
        endpoint.request(model="vision", prompt="classify", image_url="data:image/jpeg;base64,x", detail="low")
    except ShadowHTTPError as error:
        assert str(error) == "shadow_http_500:insufficient_memory:unknown"
        assert error.payload == {"detail": "Generation failed: Insufficient Memory"}
    else:
        raise AssertionError("HTTP 500 must raise ShadowHTTPError")


def test_signed_url_redaction_is_recursive():
    url = "https://signed.test/private?token=secret"
    assert _redact_url({"note": f"saw {url}", "nested": [url]}, url) == {
        "note": "saw [REDACTED_SIGNED_IMAGE_URL]", "nested": ["[REDACTED_SIGNED_IMAGE_URL]"]
    }


def test_kimi_trailing_control_token_is_cleaned_without_changing_inner_text():
    text = '{"note":"keep <|im_end|> here","category":["Tops"]}<|im_end|>\n'
    assert _clean_response_text(text) == '{"note":"keep <|im_end|> here","category":["Tops"]}'


def test_category_and_subtype_accept_scalar_or_array():
    assert _coerce_prediction_scalars({
        "category": ["Tops"], "subtype": "Blouse", "color": ["White"],
    }) == {"category": "Tops", "subtype": "Blouse", "color": ["White"]}


def test_candidate_text_repairs_only_approved_equivalent_shapes():
    repaired, actions = _repair_candidate_text(json.dumps({
        "category": ["Tops"],
        "subtype": ["T-shirt"],
        "occasion_scores": {"Everyday": 0.8},
        "seasons": ["All-Season"],
    }), taxonomy={"seasons": ["Spring", "Summer", "Fall", "Winter"]})
    payload = json.loads(repaired)
    assert payload["category"] == "Tops"
    assert payload["subtype"] == "T-shirt"
    assert payload["occasion_scores"] == [{"occasion": "Everyday", "score": 0.8}]
    assert payload["seasons"] == ["Spring", "Summer", "Fall", "Winter"]
    assert payload["warnings"] == []
    assert actions == [
        "scalarize_category", "scalarize_subtype", "reshape_occasion_scores",
        "default_empty_warnings", "expand_legacy_all_season",
    ]


def test_candidate_text_repairs_safe_taxonomy_and_nullable_shapes():
    repaired, actions = _repair_candidate_text(json.dumps({
        "category": "Shoes",
        "subtype": "Boot",
        "color": "Multicolor",
        "color_tones": [{"color": "Black"}, {"color": "Beige"}],
        "wearing_profile": {"wearing_modes": []},
        "warnings": [],
    }), taxonomy={
        "subtypes": {"Shoes": ["Boots"]},
        "colors": ["Black", "Beige", "Multicolor"],
    })
    payload = json.loads(repaired)
    assert payload["subtype"] == "Boots"
    assert payload["color"] == "Black, Beige"
    assert payload["wearing_profile"]["requires_inner_layer"] is None
    assert actions == [
        "normalize_subtype_alias:Boot->Boots",
        "default_requires_inner_layer_null",
        "expand_multicolor_from_color_tones",
    ]


def test_recognition_cost_uses_cached_rate():
    assert _estimated_usage_cost(
        {"input_tokens": 1000, "cached_input_tokens": 250, "output_tokens": 100},
        {"input": 1.0, "cached_input": 0.5, "output": 2.0},
    ) == 0.001075


def test_schema_prediction_is_available_before_taxonomy_validation():
    payload = {
        "category": "Accessories", "subtype": "Shoulder Bag", "color": "Red",
        "color_tones": [], "seasons": ["Spring"], "style": "Casual",
        "occasion_scores": [{"occasion": "Everyday", "score": 0.8}],
        "material": None, "pattern": None, "fit": None, "length": None,
        "sleeve_length": None, "neckline": None, "layering_role": None,
        "wearing_profile": {
            "layering_region": None, "lower_layer_role": None,
            "can_wear_alone": None, "can_layer_over": None,
            "can_layer_under": None, "requires_inner_layer": None,
            "closure_type": None, "layering_bulk": None, "outer_capacity": None,
            "material_stiffness": None, "hood_volume": None, "sleeve_volume": None,
            "wearing_modes": [], "evidence": None,
        },
        "warmth_level": None, "formality_score": 2, "confidence": 0.9,
        "notes": None, "warnings": [],
    }
    prediction, _, actions, raw_valid = _schema_prediction_with_local_repairs(
        json.dumps(payload), taxonomy={"seasons": ["Spring", "Summer", "Fall", "Winter"]},
    )
    assert prediction["category"] == "Accessories"
    assert prediction["subtype"] == "Shoulder Bag"
    assert actions == []
    assert raw_valid is True


def test_local_image_resize_preserves_aspect_ratio_and_returns_data_url():
    source = BytesIO()
    Image.new("RGB", (1200, 600), "white").save(source, format="JPEG")

    def handler(request: httpx.Request):
        assert str(request.url) == "https://signed.test/private"
        return httpx.Response(200, content=source.getvalue())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    image_input, audit = _resized_image_input(
        "https://signed.test/private", max_dimension=448, client=client, timeout=10,
    )
    assert image_input.startswith("data:image/jpeg;base64,")
    assert (audit["request_width"], audit["request_height"]) == (448, 224)
    assert audit["original_width"] == 1200
    assert audit["original_height"] == 600
    assert audit["request_bytes"] < audit["source_bytes"]
    assert len(audit["request_sha256"]) == 64


def test_summary_separates_production_agreement_from_manual_ground_truth(tmp_path):
    references = [{
        "item_id": "item-1", "production": {"category": "Tops", "subtype": "T-shirt", "color": "Blue"},
        "manual_confirmation": {"category": "Activewear", "subtype": "Workout Top"},
    }]
    write_json_atomic(tmp_path / "references.json", references)
    write_json_atomic(tmp_path / "results" / "item-1.json", {
        "status": "succeeded", "latency_seconds": 1.0, "usage": {"input_tokens": 10, "output_tokens": 5},
        "syntax_prediction": {"category": "Activewear", "subtype": "Workout Top", "color": "Blue"},
        "normalized_prediction": {"category": "Activewear", "subtype": "Workout Top", "color": "Blue"},
    })
    write_json_atomic(tmp_path / "run_manifest.json", {
        "candidate": {"pricing_usd_per_million": {"input": 1.0, "cached_input": 0.5, "output": 2.0}}
    })
    summary = summarize_run(tmp_path)
    assert summary["production_agreement"]["fields"]["category"]["accuracy"] == 0
    assert summary["manual_ground_truth"]["fields"]["category"]["accuracy"] == 1
    assert summary["syntax_prediction_agreement"]["fields"]["category"]["accuracy"] == 0
    assert summary["syntax_manual_ground_truth"]["fields"]["category"]["accuracy"] == 1
    assert summary["performance"]["estimated_cost_usd"] == 0.00002
    saved_summary = json.loads((tmp_path / "summary.json").read_text())
    assert digest(saved_summary) == digest(summary)


def test_reparse_persists_syntax_prediction_when_contract_validation_fails(tmp_path):
    write_json_atomic(tmp_path / "taxonomy.json", {
        "recognition_taxonomy": {},
        "allowed_categories": [],
        "allowed_taxonomy": {},
    })
    write_json_atomic(tmp_path / "references.json", [{
        "item_id": "item-1",
        "production": {"category": "Tops", "subtype": "T-shirt"},
        "manual_confirmation": None,
    }])
    write_json_atomic(tmp_path / "results" / "item-1.json", {
        "status": "failed",
        "cleaned_response_text": '{"category": "Tops", "subtype": "T-shirt"}',
        "raw_response_payload": {},
        "error": {"type": "ValidationError"},
    })
    write_json_atomic(tmp_path / "run_manifest.json", {"candidate": {}})

    summary = reparse_results(tmp_path)

    saved = json.loads((tmp_path / "results" / "item-1.json").read_text())
    assert saved["syntax_prediction"]["category"] == "Tops"
    assert summary["items"]["json_syntax_valid"] == 1
