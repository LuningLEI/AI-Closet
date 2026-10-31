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

    def response(self, *, model: str, input: list[dict[str, Any]], timeout: float,
                 schema: type[BaseModel] | dict[str, Any] | None = None,
                 schema_name: str | None = None) -> AIResult:
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
            except ValueError:
                code = None
            raise OutfitModelError(response.status_code, code if isinstance(code, str) else None,
                                   response.headers.get("x-request-id"))
        return AIResult(response.json())

    def embedding(self, *, model: str, text: str, dimensions: int,
                  timeout: float) -> tuple[list[float], dict[str, Any]]:
        response = self.client.post(f"{self.base_url}/embeddings", headers=self._headers(),
                                    json={"model": model, "input": text, "dimensions": dimensions},
                                    timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return [float(value) for value in payload["data"][0]["embedding"]], payload.get("usage") or {}


def build_ai_gateway() -> AIGateway:
    if settings.ai_provider not in {"openai", "openai-compatible"}:
        raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
    return OpenAICompatibleGateway()
