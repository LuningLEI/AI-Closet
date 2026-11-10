"""Vendor-neutral AI transport used by every production model call.

The application owns prompts, schemas and retry policy.  This module owns the
provider protocol, authentication and HTTP response parsing so OpenAI-compatible
providers (OpenAI, vLLM, hosted Qwen, etc.) can be selected by configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.outfits.diagnostics import OutfitModelError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class AIResult:
    payload: dict[str, Any]

    @property
    def text(self) -> str:
        direct = self.payload.get("output_text")
        if isinstance(direct, str) and direct:
            return direct
        return "\n".join(
            block.get("text", "")
            for output in self.payload.get("output", [])
            for block in output.get("content", [])
            if block.get("type") in {"output_text", "text"}
        )

    @property
    def usage(self) -> dict[str, Any]:
        value = self.payload.get("usage")
        return value if isinstance(value, dict) else {}


class AIGateway(Protocol):
    def response(self, *, model: str, input: list[dict[str, Any]], timeout: float,
                 schema: type[BaseModel] | dict[str, Any] | None = None,
                 schema_name: str | None = None) -> AIResult: ...

    def embedding(self, *, model: str, text: str, dimensions: int,
                  timeout: float) -> tuple[list[float], dict[str, Any]]: ...


class OpenAICompatibleGateway:
    """Responses/Embeddings client for any OpenAI-compatible HTTP endpoint."""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 client: httpx.Client | None = None) -> None:
        self.api_key = api_key if api_key is not None else settings.ai_api_key
        self.base_url = (base_url or settings.ai_base_url).rstrip("/")
        self.client = client or httpx.Client(http2=False)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("AI_API_KEY is required for this model call")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _assert_model_allowed(model: str) -> None:
        if settings.ai_allowed_models and model not in settings.ai_allowed_models:
            raise ValueError(f"Model is not in AI_ALLOWED_MODELS: {model}")

    def response(self, *, model: str, input: list[dict[str, Any]], timeout: float,
                 schema: type[BaseModel] | dict[str, Any] | None = None,
                 schema_name: str | None = None) -> AIResult:
        self._assert_model_allowed(model)
        body: dict[str, Any] = {"model": model, "input": input}
        if schema is not None:
            document = schema.model_json_schema() if isinstance(schema, type) and issubclass(schema, BaseModel) else schema
            name = schema_name or (schema.__name__ if isinstance(schema, type) else "structured_response")
            body["text"] = {"format": {"type": "json_schema", "name": name,
                                         "schema": document, "strict": True}}
        response = self.client.post(f"{self.base_url}/responses", headers=self._headers(),
                                    json=body, timeout=timeout)
        if response.is_error:
            try:
                error = response.json().get("error", {})
                code = error.get("code") if isinstance(error, dict) else None
                message = error.get("message") if isinstance(error, dict) else None
            except ValueError:
                code = None
                message = None
            raise OutfitModelError(response.status_code, code if isinstance(code, str) else None,
                                   response.headers.get("x-request-id"), message)
        return AIResult(response.json())

    def embedding(self, *, model: str, text: str, dimensions: int,
                  timeout: float) -> tuple[list[float], dict[str, Any]]:
        self._assert_model_allowed(model)
        response = self.client.post(f"{self.base_url}/embeddings", headers=self._headers(),
                                    json={"model": model, "input": text, "dimensions": dimensions},
                                    timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return [float(value) for value in payload["data"][0]["embedding"]], payload.get("usage") or {}


class OpenAIChatCompletionsGateway(OpenAICompatibleGateway):
    """OpenAI-compatible Chat Completions transport for hosted open-weight VLMs.

    The application-facing input remains the Responses-shaped contract used by
    recognition and outfit services.  Translation is isolated here so business
    logic and frozen prompts remain identical across providers.
    """

    def __init__(self, *, schema_mode: str = "json-schema", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if schema_mode not in {"json-schema", "json-object", "none"}:
            raise ValueError(f"Unsupported chat schema mode: {schema_mode}")
        self.schema_mode = schema_mode

    @staticmethod
    def _messages(input: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = []
        for message in input:
            content = []
            raw_content = message.get("content") or []
            if isinstance(raw_content, str):
                raw_content = [{"type": "input_text", "text": raw_content}]
            for block in raw_content:
                kind = block.get("type")
                if kind in {"input_text", "text"}:
                    content.append({"type": "text", "text": block.get("text", "")})
                elif kind in {"input_image", "image_url"}:
                    image = block.get("image_url")
                    if isinstance(image, dict):
                        image_value = dict(image)
                    else:
                        image_value = {"url": image}
                    if block.get("detail") and "detail" not in image_value:
                        image_value["detail"] = block["detail"]
                    content.append({"type": "image_url", "image_url": image_value})
                else:
                    raise ValueError(f"Unsupported multimodal content type: {kind}")
            messages.append({"role": message.get("role", "user"), "content": content})
        return messages

    def response(self, *, model: str, input: list[dict[str, Any]], timeout: float,
                 schema: type[BaseModel] | dict[str, Any] | None = None,
                 schema_name: str | None = None) -> AIResult:
        self._assert_model_allowed(model)
        body: dict[str, Any] = {"model": model, "messages": self._messages(input)}
        if schema is not None and self.schema_mode != "none":
            if self.schema_mode == "json-object":
                body["response_format"] = {"type": "json_object"}
            else:
                document = schema.model_json_schema() if isinstance(schema, type) and issubclass(schema, BaseModel) else schema
                name = schema_name or (schema.__name__ if isinstance(schema, type) else "structured_response")
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": document, "strict": True},
                }
        response = self.client.post(
            f"{self.base_url}/chat/completions", headers=self._headers(), json=body, timeout=timeout,
        )
        if response.is_error:
            try:
                payload = response.json()
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                code = error.get("code") if isinstance(error, dict) else None
                message = error.get("message") if isinstance(error, dict) else None
                # OpenAI-compatible providers do not share one error envelope.
                # Preserve only the provider's short diagnostic message; never
                # persist the request body, signed image URLs, or credentials.
                if not isinstance(message, str) and isinstance(payload, dict):
                    detail = payload.get("detail")
                    if isinstance(detail, str):
                        message = detail
                    elif isinstance(detail, dict):
                        message = detail.get("message") or detail.get("msg")
                    elif isinstance(payload.get("message"), str):
                        message = payload["message"]
                if not isinstance(code, str) and isinstance(payload, dict):
                    root_code = payload.get("code")
                    code = root_code if isinstance(root_code, str) else None
            except ValueError:
                code = None
                message = None
            raise OutfitModelError(
                response.status_code, code if isinstance(code, str) else None,
                response.headers.get("x-request-id"),
                message,
            )
        payload = response.json()
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") if isinstance(choice, dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        if isinstance(content, list):
            content = "\n".join(
                str(block.get("text") or "") for block in content if isinstance(block, dict)
            )
        normalized = dict(payload)
        normalized["output_text"] = content if isinstance(content, str) else ""
        normalized["finish_reason"] = choice.get("finish_reason") if isinstance(choice, dict) else None
        return AIResult(normalized)


def build_ai_gateway() -> AIGateway:
    return build_configured_gateway(
        provider=settings.ai_provider, api_key=settings.ai_api_key,
        base_url=settings.ai_base_url, schema_mode=settings.ai_chat_schema_mode,
    )


def build_configured_gateway(*, provider: str, api_key: str | None, base_url: str,
                             schema_mode: str = "json-schema") -> AIGateway:
    """Build one endpoint without changing routing for unrelated AI stages."""
    if provider in {"openai", "openai-compatible", "responses"}:
        return OpenAICompatibleGateway(api_key=api_key, base_url=base_url)
    if provider in {"chat-completions", "openai-chat-compatible"}:
        return OpenAIChatCompletionsGateway(
            api_key=api_key, base_url=base_url, schema_mode=schema_mode,
        )
    raise ValueError(f"Unsupported AI provider: {provider}")


def build_recognition_gateway() -> AIGateway:
    return build_configured_gateway(
        provider=settings.recognition_ai_provider,
        api_key=settings.recognition_ai_api_key,
        base_url=settings.recognition_ai_base_url,
        schema_mode=settings.recognition_ai_schema_mode,
    )


def build_embedding_gateway() -> AIGateway:
    # Embeddings stay on their proven endpoint when recognition/outfit VLMs are
    # routed to hosted open-weight providers.
    return OpenAICompatibleGateway(
        api_key=settings.openai_api_key, base_url="https://api.openai.com/v1",
    )


def build_outfit_generation_gateway() -> AIGateway:
    return build_configured_gateway(
        provider=settings.outfit_generation_ai_provider,
        api_key=settings.outfit_generation_ai_api_key,
        base_url=settings.outfit_generation_ai_base_url,
        schema_mode=settings.outfit_generation_ai_schema_mode,
    )


def build_outfit_visual_gateway() -> AIGateway:
    return build_configured_gateway(
        provider=settings.outfit_visual_ai_provider,
        api_key=settings.outfit_visual_ai_api_key,
        base_url=settings.outfit_visual_ai_base_url,
        schema_mode=settings.outfit_visual_ai_schema_mode,
    )
