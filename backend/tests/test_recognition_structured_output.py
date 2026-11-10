from __future__ import annotations

import json
from typing import Any

import pytest

from app.ai.gateway import AIResult, OpenAICompatibleGateway
from app.core.config import settings
from app.models.recognition_output import (
    RecognitionCandidateV1,
    recognition_candidate_schema,
    resolve_recognition_taxonomy,
)
from app.services.recognition_output import (
    RecognitionJSONSyntaxError,
    RecognitionRewriteFailed,
    RecognitionSchemaError,
    RecognitionSemanticError,
    TargetedRecognitionRetryFailed,
    parse_recognition_candidate,
)
from app.services.recognition_service import ClothingRecognitionService
from app.services.taxonomy import OCCASIONS


def valid_payload(*, occasions: list[str] | None = None) -> dict[str, Any]:
    return {
        "category": "Tops",
        "subtype": "T-shirt",
        "color": "Blue",
        "color_tones": [
            {"color": "Blue", "hue": 210.0, "saturation": 0.5, "lightness": 0.5, "evidence": "blue fabric"}
        ],
        "seasons": ["Spring", "Summer"],
        "style": "Casual",
        "occasion_scores": [
            {"occasion": occasion, "score": 0.8 if occasion == "Everyday" else 0.1}
            for occasion in (occasions or OCCASIONS)
        ],
        "material": None,
        "pattern": "Solid",
        "fit": "Regular",
        "length": "Hip",
        "sleeve_length": "Short Sleeve",
        "neckline": "Crew",
        "layering_role": "Standalone",
        "wearing_profile": {
            "layering_region": "upper_body",
            "lower_layer_role": None,
            "can_wear_alone": True,
            "can_layer_over": False,
            "can_layer_under": True,
            "requires_inner_layer": False,
            "closure_type": "pullover",
            "layering_bulk": "low",
            "outer_capacity": None,
            "material_stiffness": "soft",
            "hood_volume": "none",
            "sleeve_volume": "regular",
            "wearing_modes": ["standalone", "inner_layer"],
            "evidence": "opaque lightweight top",
        },
        "warmth_level": 1,
        "formality_score": 1,
        "confidence": 0.9,
        "notes": "A blue casual T-shirt.",
        "warnings": [],
    }


class Gateway:
    def __init__(self, *payloads: dict[str, Any] | Exception) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, Any]] = []

    def response(self, **kwargs: Any) -> AIResult:
        self.calls.append(kwargs)
        value = self.payloads.pop(0)
        if isinstance(value, Exception):
            raise value
        return AIResult(value)

    def embedding(self, **kwargs: Any) -> tuple[list[float], dict[str, Any]]:
        raise AssertionError("embedding is outside recognition schema tests")


def response_for(value: dict[str, Any] | str, **metadata: Any) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value)
    return {"output_text": text, **metadata}


def test_runtime_schema_requires_every_field_and_forbids_extras():
    taxonomy = resolve_recognition_taxonomy()
    schema = recognition_candidate_schema(taxonomy)
    assert set(schema["required"]) == set(RecognitionCandidateV1.model_fields)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["category"]["enum"] == taxonomy["categories"]
    assert schema["$defs"]["RecognitionWearingProfile"]["additionalProperties"] is False
    assert set(schema["$defs"]["RecognitionWearingProfile"]["required"]) == set(
        RecognitionCandidateV1.model_fields["wearing_profile"].annotation.model_fields
    )


def test_valid_output_is_strictly_parsed_and_semantically_validated():
    parsed = parse_recognition_candidate(
        AIResult(response_for(valid_payload())),
        taxonomy=resolve_recognition_taxonomy(),
    )
    assert parsed.candidate.category == "Tops"
    assert parsed.candidate.material is None
    assert parsed.formatting_repaired is False


def test_safe_payload_normalization_runs_in_production_parser():
    payload = valid_payload()
    payload.update(
        category="Shoes",
        subtype="Boot",
        color="Multicolor",
        color_tones=[
            {"color": "Black", "hue": 0.0, "saturation": 0.0, "lightness": 0.1,
             "evidence": "black leather"},
            {"color": "Beige", "hue": 40.0, "saturation": 0.3, "lightness": 0.7,
             "evidence": "beige trim"},
        ],
    )
    del payload["wearing_profile"]["requires_inner_layer"]

    parsed = parse_recognition_candidate(
        AIResult(response_for(payload)),
        taxonomy=resolve_recognition_taxonomy(),
    )

    assert parsed.candidate.subtype == "Boots"
    assert parsed.candidate.color == "Black, Beige"
    assert parsed.candidate.wearing_profile.requires_inner_layer is None
    assert parsed.formatting_repaired is True
    assert parsed.repair_actions == (
        "normalize_subtype_alias:Boot->Boots",
        "default_requires_inner_layer_null",
        "expand_multicolor_from_color_tones",
    )


def test_safe_cross_field_normalization_drops_only_contradictions():
    payload = valid_payload()
    payload["category"] = "Outerwear"
    payload["subtype"] = "Pullover"
    payload["color_tones"].append(
        {"color": "Black", "hue": 0.0, "saturation": 0.0, "lightness": 0.1,
         "evidence": "conflicting auxiliary estimate"}
    )
    payload["wearing_profile"].update(
        can_layer_over=False,
        closure_type="pullover",
        wearing_modes=["standalone", "outer_layer_closed", "outer_layer_open"],
    )

    parsed = parse_recognition_candidate(
        AIResult(response_for(payload)), taxonomy=resolve_recognition_taxonomy(),
    )

    assert parsed.candidate.subtype is None
    assert [tone.color for tone in parsed.candidate.color_tones] == ["Blue"]
    assert parsed.candidate.wearing_profile.wearing_modes == ["standalone"]
    assert parsed.repair_actions == (
        "drop_category_incompatible_subtype:Pullover",
        "drop_color_tones_outside_primary_color",
        "drop_modes_contradicting_capabilities",
    )


@pytest.mark.parametrize(
    "wrapper",
    [
        lambda body: f"```json\n{body}\n```",
        lambda body: f"{body}<|im_end|>",
        lambda body: f"Here is the requested object:\n{body}\nDone.",
    ],
)
def test_formatting_wrappers_are_repaired_without_another_visual_call(wrapper):
    gateway = Gateway(response_for(wrapper(json.dumps(valid_payload()))))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.category == "Tops"
    assert len(gateway.calls) == 1


def test_non_truncated_invalid_json_uses_text_only_rewrite():
    gateway = Gateway(response_for('{"category": truue}'), response_for(valid_payload()))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.category == "Tops"
    assert len(gateway.calls) == 2
    assert gateway.calls[1]["model"] == settings.recognition_repair_model
    assert all(block.get("type") != "input_image" for message in gateway.calls[1]["input"]
               for block in (message.get("content") if isinstance(message.get("content"), list) else []))


def test_trailing_comma_uses_text_only_rewrite():
    gateway = Gateway(response_for('{"category": "Tops",}'), response_for(valid_payload()))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.category == "Tops"
    assert len(gateway.calls) == 2


def test_empty_output_gets_at_most_one_targeted_visual_retry():
    gateway = Gateway({"output_text": ""}, response_for(valid_payload()))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.category == "Tops"
    assert len(gateway.calls) == 2


def test_truncated_output_gets_one_targeted_visual_retry():
    gateway = Gateway(
        response_for('{"category": "Tops"', status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
        response_for(valid_payload()),
    )
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.category == "Tops"
    assert len(gateway.calls) == 2
    retry_prompt = gateway.calls[1]["input"][0]["content"][0]["text"]
    assert "truncated_response" in retry_prompt


def test_schema_error_gets_one_text_rewrite_and_no_visual_retry():
    invalid = valid_payload()
    invalid.pop("color_tones")
    gateway = Gateway(response_for(invalid), response_for(valid_payload()))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.category == "Tops"
    assert result.output_repair["original_failure_kind"] == "schema_violation"
    assert len(gateway.calls) == 2
    assert gateway.calls[1]["schema_name"] == "clothing_recognition_repair_v1"


def test_invalid_text_rewrite_is_terminal_without_visual_cycle():
    invalid = valid_payload()
    invalid.pop("color_tones")
    gateway = Gateway(response_for(invalid), response_for(invalid), response_for(valid_payload()))
    with pytest.raises(RecognitionRewriteFailed):
        ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert len(gateway.calls) == 2


def test_text_rewrite_provider_failure_does_not_start_another_cycle():
    invalid = valid_payload()
    invalid.pop("color_tones")
    gateway = Gateway(response_for(invalid), TimeoutError("provider timeout"), response_for(valid_payload()))
    with pytest.raises(RecognitionRewriteFailed):
        ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert len(gateway.calls) == 2


def test_text_rewrite_does_not_consume_visual_retry_budget():
    invalid = valid_payload()
    invalid.pop("color_tones")
    gateway = Gateway(response_for(invalid), response_for(valid_payload()))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision(
        "https://example.test/item.jpg", max_visual_calls=1,
    )
    assert result.category == "Tops"
    assert len(gateway.calls) == 2


def test_extra_fields_are_rejected_before_normalization():
    invalid = valid_payload() | {"provider_internal_note": "ignore this"}
    with pytest.raises(RecognitionSchemaError):
        parse_recognition_candidate(AIResult(response_for(invalid)), taxonomy=resolve_recognition_taxonomy())


def test_string_null_is_not_accepted_for_nullable_attributes():
    invalid = valid_payload() | {"material": "null"}
    with pytest.raises(RecognitionSchemaError):
        parse_recognition_candidate(AIResult(response_for(invalid)), taxonomy=resolve_recognition_taxonomy())


def test_category_incompatible_subtype_is_safely_dropped_without_rewrite_call():
    invalid = valid_payload()
    invalid["subtype"] = "Boots"
    gateway = Gateway(response_for(invalid), response_for(valid_payload()))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    assert result.subtype is None
    assert len(gateway.calls) == 1


def test_occasion_scores_must_cover_runtime_taxonomy_exactly_once():
    invalid = valid_payload()
    invalid["occasion_scores"] = invalid["occasion_scores"][:-1]
    with pytest.raises(RecognitionSemanticError):
        parse_recognition_candidate(AIResult(response_for(invalid)), taxonomy=resolve_recognition_taxonomy())


def test_custom_taxonomy_is_used_by_schema_validation_and_normalization():
    custom = {
        "categories": ["Tops"],
        "subtypes": {"Tops": ["Unknown", "Corset Top"]},
        "colors": ["Unknown", "Dusty Rose"],
        "styles": ["Avant-garde"],
        "occasions": ["Concert"],
        "seasons": ["Warm Weather"],
        "lengths": ["Longline"],
        "sleeve_lengths": ["Bell Sleeve"],
    }
    payload = valid_payload(occasions=["Concert"])
    payload.update(
        subtype="Corset Top",
        color="Dusty Rose",
        color_tones=[
            {"color": "Dusty Rose", "hue": 345.0, "saturation": 0.25, "lightness": 0.7, "evidence": None}
        ],
        seasons=["Warm Weather"],
        style="Avant-garde",
        length="Longline",
        sleeve_length="Bell Sleeve",
    )
    gateway = Gateway(response_for(payload))
    result = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision(
        "https://example.test/item.jpg",
        allowed_categories=["Tops"],
        allowed_taxonomy=custom,
    )
    assert (result.subtype, result.color, result.style) == ("Corset Top", "Dusty Rose", "Avant-garde")
    assert result.color_tones[0].color == "Dusty Rose"
    schema = gateway.calls[0]["schema"]
    assert schema["properties"]["category"]["enum"] == ["Tops"]
    assert schema["$defs"]["RecognitionColorTone"]["properties"]["color"]["enum"] == [
        "Unknown",
        "Dusty Rose",
    ]


def test_multiple_items_are_reported_without_returning_multiple_garments():
    payload = valid_payload() | {"warnings": ["multiple_clothing_items"]}
    parsed = parse_recognition_candidate(AIResult(response_for(payload)), taxonomy=resolve_recognition_taxonomy())
    assert parsed.candidate.warnings == ["multiple_clothing_items"]
    gateway = Gateway(response_for(payload))
    analysis = ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision(
        "https://example.test/item.jpg"
    )
    assert analysis.warnings == ["multiple_clothing_items"]


def test_gateway_receives_runtime_json_schema():
    gateway = Gateway(response_for(valid_payload()))
    ClothingRecognitionService(gateway=gateway)._analyze_with_openai_vision("https://example.test/item.jpg")
    call = gateway.calls[0]
    assert call["schema_name"] == "clothing_recognition_v1"
    assert call["schema"]["additionalProperties"] is False


def test_openai_responses_transport_sends_strict_json_schema_format():
    class Response:
        is_error = False

        def json(self):
            return {"output_text": json.dumps(valid_payload())}

    class Client:
        def __init__(self):
            self.request: dict[str, Any] | None = None

        def post(self, url: str, **kwargs: Any):
            self.request = {"url": url, **kwargs}
            return Response()

    client = Client()
    schema = recognition_candidate_schema(resolve_recognition_taxonomy())
    OpenAICompatibleGateway(api_key="test-key", base_url="https://provider.test/v1", client=client).response(
        model="test-model",
        input=[{"role": "user", "content": []}],
        timeout=10,
        schema=schema,
        schema_name="clothing_recognition_v1",
    )
    assert client.request is not None
    body = client.request["json"]
    assert body["text"]["format"] == {
        "type": "json_schema",
        "name": "clothing_recognition_v1",
        "schema": schema,
        "strict": True,
    }
