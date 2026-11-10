import json

import httpx
import pytest

from app.ai.gateway import OpenAIChatCompletionsGateway
from app.outfits.diagnostics import OutfitModelError


def test_chat_gateway_translates_multimodal_input_and_strict_schema():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        })

    gateway = OpenAIChatCompletionsGateway(
        api_key="secret", base_url="https://provider.test/v1", schema_mode="json-schema",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = gateway.response(
        model="approved/model", timeout=10,
        input=[{"role": "user", "content": [
            {"type": "input_text", "text": "inspect"},
            {"type": "input_image", "image_url": "https://image.test/a", "detail": "low"},
        ]}],
        schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        schema_name="answer",
    )
    assert result.text == '{"ok":true}'
    assert result.payload["finish_reason"] == "stop"
    assert seen["messages"][0]["content"][1] == {
        "type": "image_url", "image_url": {"url": "https://image.test/a", "detail": "low"},
    }
    assert seen["response_format"]["json_schema"]["name"] == "answer"
    assert seen["response_format"]["json_schema"]["strict"] is True


def test_chat_gateway_normalizes_string_system_content():
    messages = OpenAIChatCompletionsGateway._messages([
        {"role": "system", "content": "Return valid JSON."},
        {"role": "user", "content": [{"type": "input_text", "text": "inspect"}]},
    ])

    assert messages == [
        {"role": "system", "content": [{"type": "text", "text": "Return valid JSON."}]},
        {"role": "user", "content": [{"type": "text", "text": "inspect"}]},
    ]


def test_chat_gateway_can_fall_back_to_json_object():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    gateway = OpenAIChatCompletionsGateway(
        api_key="secret", base_url="https://provider.test/v1", schema_mode="json-object",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    gateway.response(
        model="model", timeout=10, input=[{"role": "user", "content": []}],
        schema={"type": "object"},
    )
    assert seen["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("status,code", [(401, "invalid_api_key"), (429, "rate_limit_exceeded"), (500, "server_error")])
def test_chat_gateway_normalizes_provider_errors(status, code):
    def handler(_request: httpx.Request):
        return httpx.Response(status, json={"error": {"code": code, "message": "safe detail"}})

    gateway = OpenAIChatCompletionsGateway(
        api_key="secret", base_url="https://provider.test/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(OutfitModelError) as caught:
        gateway.response(model="model", timeout=10, input=[])
    assert caught.value.http_status == status
    assert caught.value.provider_code == code
    assert caught.value.provider_message == "safe detail"


def test_chat_gateway_rejects_unknown_schema_mode():
    with pytest.raises(ValueError, match="Unsupported chat schema mode"):
        OpenAIChatCompletionsGateway(api_key="secret", schema_mode="vendor-magic")
