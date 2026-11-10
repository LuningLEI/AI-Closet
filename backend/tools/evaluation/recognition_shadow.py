"""Offline recognition shadow evaluation with no production database writes.

Prepare freezes production and manually confirmed references. Run calls a
candidate vision endpoint and writes one atomic result per garment. Summarize
compares candidate output with both references without treating production
model agreement as human ground truth.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
from PIL import Image, ImageOps

from app.ai.gateway import AIResult
from app.models.recognition_output import (
    RecognitionCandidateV1,
    recognition_candidate_schema,
    resolve_recognition_taxonomy,
)
from app.repositories.factory import build_closet_repository
from app.services.recognition_output import parse_recognition_candidate
from app.services.recognition_output import repair_recognition_payload
from app.services.recognition_service import ClothingRecognitionService
from app.services.storage_service import StorageService
from app.services.taxonomy import merge_preferences, user_categories, user_taxonomy
from tools.evaluation.paths import evaluation_path


SCHEMA_VERSION = "recognition-shadow-v2"
STRICT_RESPONSE_FORMAT = "json-schema"
DEFAULT_OUTPUT_ROOT = evaluation_path("model_migration", "recognition_shadow")
REFERENCE_FIELDS = (
    "category", "subtype", "color", "season", "style", "occasion", "material",
    "pattern", "fit", "length", "sleeve_length", "neckline", "layering_role",
    "warmth_level", "formality_score",
)
SET_FIELDS = frozenset({"color", "season", "occasion"})
CORE_FIELDS = ("category", "subtype", "color", "season", "style", "occasion")
LOCAL_IMAGE_FORMAT = "JPEG"
LOCAL_IMAGE_QUALITY = 90
MAX_SOURCE_IMAGE_BYTES = 50 * 1024 * 1024
TRAILING_CONTROL_TOKENS = re.compile(r"(?:\s*<\|im_end\|>\s*)+$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_endpoint(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Shadow base URL must be an absolute HTTP(S) URL")
    if parts.username or parts.password:
        raise ValueError("Shadow base URL must not contain credentials")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _production_reference(item: Any) -> dict[str, Any]:
    return {field: getattr(item, field) for field in REFERENCE_FIELDS}


def _manual_reference(item: Any) -> dict[str, Any] | None:
    labels = ((item.metadata or {}).get("label_confirmation") or {}).get("labels")
    if not isinstance(labels, dict):
        return None
    result = {field: labels[field] for field in REFERENCE_FIELDS if field in labels}
    return result or None


def _balanced(items: list[Any], limit: int) -> list[Any]:
    if limit <= 0 or limit >= len(items):
        return sorted(items, key=lambda item: item.id)
    groups: dict[str, list[Any]] = defaultdict(list)
    for item in sorted(items, key=lambda candidate: candidate.id):
        groups[item.category].append(item)
    selected: list[Any] = []
    categories = sorted(groups)
    while len(selected) < limit:
        added = False
        for category in categories:
            if groups[category] and len(selected) < limit:
                selected.append(groups[category].pop(0))
                added = True
        if not added:
            break
    return selected


def prepare_run(
    *, user_id: str, model: str, base_url: str, protocol: str, detail: str,
    limit: int, output_root: Path, baseline: str | None, response_format: str,
    model_revision: str | None = None, deployment_label: str | None = None,
    input_usd_per_million: float | None = None,
    cached_input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None,
    image_max_dimension: int = 0,
    output_max_tokens: int = 0,
    repository: Any | None = None,
) -> Path:
    if response_format != STRICT_RESPONSE_FORMAT:
        raise ValueError(
            "Recognition shadow evaluations require strict JSON Schema; "
            "json-object and unstructured output are not allowed"
        )
    if limit < 0:
        raise ValueError("limit must be zero (all) or a positive item count")
    if image_max_dimension < 0:
        raise ValueError("image_max_dimension must be zero (disabled) or positive")
    if output_max_tokens < 0:
        raise ValueError("output_max_tokens must be zero (provider default) or positive")
    for name, value in {
        "input_usd_per_million": input_usd_per_million,
        "cached_input_usd_per_million": cached_input_usd_per_million,
        "output_usd_per_million": output_usd_per_million,
    }.items():
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError(f"{name} must be a non-negative finite number")
    repository = repository or build_closet_repository()
    items = [
        item for item in repository.list_items(user_id)
        if item.recognition_status in {"complete", "manual"} and item.image_path
    ]
    selected = _balanced(items, limit)
    if not selected:
        raise RuntimeError("No completed garments with stable image paths were found")

    preference_record = repository.get_preferences(user_id)
    preferences = merge_preferences(preference_record.get("preferences") or {})
    taxonomy = user_taxonomy(preferences)
    categories = user_categories(preferences)
    recognition_taxonomy = resolve_recognition_taxonomy(
        allowed_categories=categories, allowed_taxonomy=taxonomy,
    )
    output_schema = recognition_candidate_schema(recognition_taxonomy)
    service = ClothingRecognitionService()
    prompt = service._vision_prompt(
        allowed_categories=categories,
        user_profile=preferences.get("profile") or {},
        allowed_taxonomy=taxonomy,
    )
    references = []
    for item in selected:
        references.append({
            "item_id": item.id,
            "image_path": item.image_path,
            "image_revision": digest({"image_path": item.image_path, "metadata": item.metadata}),
            "production": _production_reference(item),
            "manual_confirmation": _manual_reference(item),
            "recognition_status": item.recognition_status,
            "recognition_source": item.recognition_source,
        })

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{re.sub(r'[^a-zA-Z0-9_.-]+', '-', model)[:50]}-{uuid4().hex[:8]}"
    run_dir = output_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(run_dir / "references.json", references)
    write_json_atomic(run_dir / "taxonomy.json", {
        "allowed_categories": categories,
        "allowed_taxonomy": taxonomy,
        "recognition_taxonomy": recognition_taxonomy,
        "profile_context": preferences.get("profile") or {},
    })
    write_json_atomic(run_dir / "output_schema.json", output_schema)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "state": "prepared",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "user_id": user_id,
        "candidate": {
            "model": model,
            "base_url": safe_endpoint(base_url),
            "protocol": protocol,
            "detail": detail,
            "response_format": response_format,
            "model_revision": model_revision,
            "deployment_label": deployment_label,
            "image_preprocessing": {
                "max_dimension": image_max_dimension,
                "mode": "fit-within" if image_max_dimension else "none",
                "format": LOCAL_IMAGE_FORMAT if image_max_dimension else None,
                "quality": LOCAL_IMAGE_QUALITY if image_max_dimension else None,
            },
            "output_max_tokens": output_max_tokens,
            "pricing_usd_per_million": {
                "input": input_usd_per_million,
                "cached_input": cached_input_usd_per_million,
                "output": output_usd_per_million,
            },
        },
        "reference": {
            "item_count": len(references),
            "manual_confirmation_count": sum(row["manual_confirmation"] is not None for row in references),
            "content_sha256": digest(references),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "taxonomy_sha256": digest(taxonomy),
            "output_schema_sha256": digest(output_schema),
            "baseline_snapshot": baseline,
        },
        "safety": {
            "production_writes": False,
            "production_tables_modified": [],
            "api_key_persisted": False,
            "signed_image_urls_persisted": False,
        },
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    return run_dir


def clone_run(
    *, source_run: Path, model: str, base_url: str, protocol: str,
    response_format: str, output_root: Path, model_revision: str | None = None,
    deployment_label: str | None = None, input_usd_per_million: float | None = None,
    cached_input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None, output_max_tokens: int = 0,
    image_max_dimension: int | None = None,
    prompt_suffix: str | None = None,
    prompt_variant: str | None = None,
) -> Path:
    """Create a provider run from byte-identical frozen inputs and references."""
    if response_format != STRICT_RESPONSE_FORMAT:
        raise ValueError(
            "Recognition shadow evaluations require strict JSON Schema; "
            "json-object and unstructured output are not allowed"
        )
    source_manifest = read_json(source_run / "run_manifest.json")
    if source_manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Source run does not use the current recognition shadow schema")
    if image_max_dimension is not None and image_max_dimension < 0:
        raise ValueError("image_max_dimension must be zero (disabled) or positive")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{timestamp}-{re.sub(r'[^a-zA-Z0-9_.-]+', '-', model)[:50]}-{uuid4().hex[:8]}"
    run_dir = output_root.resolve() / run_id
    (run_dir / "results").mkdir(parents=True)
    for name in ("references.json", "taxonomy.json", "output_schema.json"):
        shutil.copyfile(source_run / name, run_dir / name)
    source_prompt = (source_run / "prompt.txt").read_text(encoding="utf-8")
    prompt = source_prompt
    if prompt_suffix and prompt_suffix.strip():
        prompt = f"{source_prompt.rstrip()}\n\n{prompt_suffix.strip()}\n"
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    manifest = {
        **source_manifest,
        "run_id": run_id,
        "state": "prepared",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "completed_at": None,
        "blocked_reason": None,
        "result_count": 0,
        "candidate": {
            **source_manifest["candidate"],
            "model": model,
            "base_url": safe_endpoint(base_url),
            "protocol": protocol,
            "response_format": response_format,
            "model_revision": model_revision,
            "deployment_label": deployment_label,
            "prompt_variant": prompt_variant,
            "output_max_tokens": output_max_tokens,
            "image_preprocessing": (
                source_manifest["candidate"].get("image_preprocessing")
                if image_max_dimension is None
                else {
                    "max_dimension": image_max_dimension,
                    "mode": "fit-within" if image_max_dimension else "none",
                    "format": LOCAL_IMAGE_FORMAT if image_max_dimension else None,
                    "quality": LOCAL_IMAGE_QUALITY if image_max_dimension else None,
                }
            ),
            "pricing_usd_per_million": {
                "input": input_usd_per_million,
                "cached_input": cached_input_usd_per_million,
                "output": output_usd_per_million,
            },
        },
        "reference": {
            **source_manifest["reference"],
            "cloned_from_run": source_manifest["run_id"],
            "source_prompt_sha256": source_manifest["reference"]["prompt_sha256"],
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        },
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    return run_dir


class ShadowEndpoint:
    def __init__(self, *, base_url: str, api_key: str | None, protocol: str, timeout: float,
                 response_format: str = "none", client: httpx.Client | None = None) -> None:
        self.base_url = safe_endpoint(base_url)
        self.api_key = api_key
        self.protocol = protocol
        self.timeout = timeout
        self.response_format = response_format
        self.client = client or httpx.Client(http2=False)

    def request(
        self, *, model: str, prompt: str, image_url: str, detail: str,
        max_tokens: int = 0, schema: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.protocol != "gemini-generate-content":
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.protocol == "responses":
            body = {"model": model, "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_url, "detail": detail},
            ]}]}
            if self.response_format == "json-schema":
                if schema is None:
                    raise ValueError("json-schema response format requires a frozen schema")
                body["text"] = {"format": {
                    "type": "json_schema", "name": "clothing_recognition_v1",
                    "schema": schema, "strict": True,
                }}
            path = "/responses"
        elif self.protocol == "chat-completions":
            body = {"model": model, "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url, "detail": detail}},
            ]}]}
            if self.response_format == "json-object":
                body["response_format"] = {"type": "json_object"}
            elif self.response_format == "json-schema":
                if schema is None:
                    raise ValueError("json-schema response format requires a frozen schema")
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "clothing_recognition_v1", "schema": schema, "strict": True,
                    },
                }
            path = "/chat/completions"
        elif self.protocol == "gemini-generate-content":
            if not image_url.startswith("data:") or ";base64," not in image_url:
                raise ValueError(
                    "Gemini shadow evaluation requires an inline base64 image; "
                    "set --image-max-dimension to a positive value"
                )
            media_header, image_data = image_url.split(",", 1)
            mime_type = media_header.removeprefix("data:").split(";", 1)[0]
            generation_config: dict[str, Any] = {
                "temperature": 0,
                "responseMimeType": "application/json",
            }
            if self.response_format == "json-schema":
                if schema is None:
                    raise ValueError("json-schema response format requires a frozen schema")
                generation_config["responseJsonSchema"] = schema
            if max_tokens > 0:
                generation_config["maxOutputTokens"] = max_tokens
            body = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {"mimeType": mime_type, "data": image_data}},
                    ],
                }],
                "generationConfig": generation_config,
            }
            if self.api_key:
                headers["x-goog-api-key"] = self.api_key
            path = f"/models/{quote(model, safe='')}:generateContent"
        else:  # pragma: no cover - argparse prevents this
            raise ValueError(f"Unsupported shadow protocol: {self.protocol}")
        if max_tokens > 0 and self.protocol != "gemini-generate-content":
            body["max_output_tokens" if self.protocol == "responses" else "max_tokens"] = max_tokens
        response = self.client.post(self.base_url + path, headers=headers, json=body, timeout=self.timeout)
        if response.is_error:
            code = None
            error_payload: Any = None
            try:
                error_payload = response.json()
                error = error_payload.get("error") or {}
                code = error.get("code") if isinstance(error, dict) else None
                detail = error_payload.get("detail")
                if not code and isinstance(detail, str) and "Insufficient Memory" in detail:
                    code = "insufficient_memory"
            except ValueError:
                error_payload = {"body": response.text[:2000]}
            request_id = response.headers.get("x-request-id")
            raise ShadowHTTPError(
                status_code=response.status_code,
                code=code or "unknown",
                request_id=request_id or "unknown",
                payload=error_payload,
            )
        payload = response.json()
        if self.protocol == "responses":
            text = payload.get("output_text") or "\n".join(
                block.get("text", "")
                for output in payload.get("output", [])
                for block in output.get("content", [])
                if block.get("type") in {"output_text", "text"}
            )
        elif self.protocol == "gemini-generate-content":
            text = "\n".join(
                str(part.get("text") or "")
                for candidate in payload.get("candidates", [])
                for part in ((candidate.get("content") or {}).get("parts") or [])
                if isinstance(part, dict) and part.get("text")
            )
        else:
            content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content")
            text = content if isinstance(content, str) else "\n".join(
                str(block.get("text") or "") for block in (content or []) if isinstance(block, dict)
            )
        if not text:
            raise ValueError("Candidate response did not contain text")
        return payload, text


class ShadowHTTPError(RuntimeError):
    def __init__(
        self, *, status_code: int, code: str, request_id: str, payload: Any,
    ) -> None:
        super().__init__(f"shadow_http_{status_code}:{code}:{request_id}")
        self.status_code = status_code
        self.code = code
        self.payload = payload


def _usage(payload: dict[str, Any]) -> dict[str, int | None]:
    gemini_usage = payload.get("usageMetadata")
    if isinstance(gemini_usage, dict):
        candidate_tokens = int(gemini_usage.get("candidatesTokenCount") or 0)
        reasoning_tokens = int(gemini_usage.get("thoughtsTokenCount") or 0)
        return {
            "input_tokens": gemini_usage.get("promptTokenCount"),
            "cached_input_tokens": gemini_usage.get("cachedContentTokenCount"),
            # Gemini bills thought tokens at the output-token rate. Keep the
            # subset separately for audit while output_tokens remains billable.
            "output_tokens": candidate_tokens + reasoning_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    return {
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
        "cached_input_tokens": details.get("cached_tokens", usage.get("cached_input_tokens")),
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
    }


def _safe_error(error: Exception) -> dict[str, str]:
    message = str(error)
    if not message.startswith("shadow_http_"):
        message = type(error).__name__
    return {"type": type(error).__name__, "code": message[:200]}


def _redact_url(value: Any, image_url: str) -> Any:
    """Remove the expiring private URL from all candidate-controlled output."""
    if not image_url:
        return value
    if isinstance(value, str):
        return value.replace(image_url, "[REDACTED_SIGNED_IMAGE_URL]")
    if isinstance(value, list):
        return [_redact_url(item, image_url) for item in value]
    if isinstance(value, dict):
        return {key: _redact_url(item, image_url) for key, item in value.items()}
    return value


def _redact_request_image(value: Any, request_image: str, signed_url: str) -> Any:
    """Remove both the private URL and any generated data URL from audit output."""
    redacted = _redact_url(value, signed_url)
    if not request_image or request_image == signed_url:
        return redacted
    if isinstance(redacted, str):
        return redacted.replace(request_image, "[REDACTED_REQUEST_IMAGE]")
    if isinstance(redacted, list):
        return [_redact_request_image(item, request_image, signed_url) for item in redacted]
    if isinstance(redacted, dict):
        return {
            key: _redact_request_image(item, request_image, signed_url)
            for key, item in redacted.items()
        }
    return redacted


def _clean_response_text(text: str) -> str:
    """Strip only known trailing model-control tokens, preserving raw text separately."""
    return TRAILING_CONTROL_TOKENS.sub("", text).strip()


def _repair_candidate_text(
    text: str,
    *,
    taxonomy: dict[str, Any],
) -> tuple[str, list[str]]:
    """Apply only lossless or explicitly defined legacy-shape repairs.

    The original provider text remains in the audit record.  These repairs do
    not infer garment attributes: they reshape equivalent JSON, apply explicit
    taxonomy aliases, add missing nullable structure, or expand values already
    present elsewhere in the same response.
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text, []
    if not isinstance(parsed, dict):
        return text, []

    repaired, actions = repair_recognition_payload(parsed, taxonomy=taxonomy)

    if not actions:
        return text, []
    return json.dumps(repaired, ensure_ascii=False, separators=(",", ":")), list(actions)


def _parse_with_local_repairs(
    text: str,
    *,
    taxonomy: dict[str, Any],
) -> tuple[Any, str, list[str], bool]:
    """Parse strict output, repairing approved text shapes without a model call."""
    try:
        parsed = parse_recognition_candidate(
            AIResult({"output_text": text}), taxonomy=taxonomy,
        )
        return parsed, text, [], True
    except Exception as original_error:
        repaired_text, actions = _repair_candidate_text(text, taxonomy=taxonomy)
        if not actions:
            raise original_error
        parsed = parse_recognition_candidate(
            AIResult({"output_text": repaired_text}), taxonomy=taxonomy,
        )
        return parsed, repaired_text, actions, False


def _schema_prediction_with_local_repairs(
    text: str,
    *,
    taxonomy: dict[str, Any],
) -> tuple[dict[str, Any], str, list[str], bool]:
    """Return a schema-valid diagnostic prediction before taxonomy checks."""
    try:
        parsed = json.loads(text)
        return RecognitionCandidateV1.model_validate(parsed).model_dump(), text, [], True
    except Exception as original_error:
        repaired_text, actions = _repair_candidate_text(text, taxonomy=taxonomy)
        if not actions:
            raise original_error
        parsed = json.loads(repaired_text)
        candidate = RecognitionCandidateV1.model_validate(parsed)
        return candidate.model_dump(), repaired_text, actions, False


def _coerce_prediction_scalars(prediction: dict[str, Any]) -> dict[str, Any]:
    """Accept scalar or list output for fields that production normalization treats as scalar."""
    coerced = dict(prediction)
    for field in ("category", "subcategory", "subtype"):
        value = coerced.get(field)
        if isinstance(value, list):
            coerced[field] = next(
                (str(item).strip() for item in value if str(item).strip()),
                None,
            )
    return coerced


def _estimated_usage_cost(
    usage: dict[str, Any] | None,
    pricing: dict[str, Any],
) -> float:
    if pricing.get("input") is None or pricing.get("output") is None:
        raise ValueError("Recognition shadow pricing is required for budget enforcement")
    usage = usage or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    cached_tokens = int(usage.get("cached_input_tokens") or 0)
    cached_rate = pricing.get("cached_input")
    if cached_rate is None:
        cached_rate = pricing["input"]
    return (
        max(0, input_tokens - cached_tokens) * float(pricing["input"])
        + cached_tokens * float(cached_rate)
        + int(usage.get("output_tokens") or 0) * float(pricing["output"])
    ) / 1_000_000


def _resized_image_input(
    image_url: str, *, max_dimension: int, client: httpx.Client, timeout: float,
) -> tuple[str, dict[str, Any]]:
    """Download and resize a private image in memory for a constrained local endpoint."""
    if max_dimension <= 0:
        return image_url, {"applied": False}
    response = client.get(image_url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    source = response.content
    if not source or len(source) > MAX_SOURCE_IMAGE_BYTES:
        raise ValueError("Source image is empty or exceeds the shadow evaluation limit")
    with Image.open(io.BytesIO(source)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        original_size = image.size
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        resized_size = image.size
        output = io.BytesIO()
        image.save(output, format=LOCAL_IMAGE_FORMAT, quality=LOCAL_IMAGE_QUALITY, optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    request_bytes = output.getvalue()
    return f"data:image/jpeg;base64,{encoded}", {
        "applied": True,
        "max_dimension": max_dimension,
        "original_width": original_size[0],
        "original_height": original_size[1],
        "request_width": resized_size[0],
        "request_height": resized_size[1],
        "source_bytes": len(source),
        "request_bytes": len(request_bytes),
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "format": LOCAL_IMAGE_FORMAT,
        "quality": LOCAL_IMAGE_QUALITY,
    }


def run_shadow(
    run_dir: Path, *, api_key_env: str, timeout: float, max_items: int,
    max_attempts: int, delay_seconds: float, retry_failures: bool,
    budget_usd: float = 10.0,
    allow_no_api_key: bool = False,
    storage: StorageService | None = None, client: httpx.Client | None = None,
) -> dict[str, Any]:
    if (
        max_items < 0 or max_attempts < 1 or delay_seconds < 0
        or timeout <= 0 or budget_usd <= 0
    ):
        raise ValueError("max-items/delay must be non-negative and timeout/max-attempts must be positive")
    manifest_path = run_dir / "run_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported recognition shadow run schema")
    api_key = os.getenv(api_key_env)
    if not api_key and not allow_no_api_key:
        raise RuntimeError(f"Candidate API key is missing from environment variable {api_key_env}")
    references = read_json(run_dir / "references.json")
    if digest(references) != manifest["reference"]["content_sha256"]:
        raise RuntimeError("Frozen references do not match the run manifest")
    taxonomy = read_json(run_dir / "taxonomy.json")
    output_schema = read_json(run_dir / "output_schema.json")
    if digest(output_schema) != manifest["reference"]["output_schema_sha256"]:
        raise RuntimeError("Frozen output schema does not match the run manifest")
    prompt = (run_dir / "prompt.txt").read_text(encoding="utf-8")
    if hashlib.sha256(prompt.encode()).hexdigest() != manifest["reference"]["prompt_sha256"]:
        raise RuntimeError("Frozen prompt does not match the run manifest")

    candidate = manifest["candidate"]
    if candidate.get("response_format") != STRICT_RESPONSE_FORMAT:
        raise RuntimeError(
            "Prepared recognition run is not configured for strict JSON Schema; "
            "clone or prepare a new strict-schema run before inference"
        )
    pricing = candidate.get("pricing_usd_per_million") or {}
    # Fail closed: a paid batch may not run when the harness cannot account
    # for its cost against the approved budget.
    _estimated_usage_cost({}, pricing)
    existing_results = [
        read_json(path) for path in (run_dir / "results").glob("*.json")
    ]
    spent = sum(
        _estimated_usage_cost(result.get("usage"), pricing)
        for result in existing_results
        if result.get("usage") is not None
    )
    endpoint = ShadowEndpoint(
        base_url=candidate["base_url"], api_key=api_key, protocol=candidate["protocol"],
        timeout=timeout, response_format=candidate.get("response_format", "none"), client=client,
    )
    storage = storage or StorageService()
    service = ClothingRecognitionService()
    manifest.update(state="running", updated_at=utc_now())
    write_json_atomic(manifest_path, manifest)

    processed = 0
    blocked_reason: str | None = None
    for reference in references:
        if spent >= budget_usd:
            blocked_reason = "evaluation_budget_exhausted"
            break
        result_path = run_dir / "results" / f"{reference['item_id']}.json"
        if result_path.exists() and not (retry_failures and read_json(result_path).get("status") == "failed"):
            continue
        if max_items > 0 and processed >= max_items:
            break
        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "item_id": reference["item_id"],
            "status": "failed",
            "attempts": 0,
            "started_at": utc_now(),
        }
        for attempt in range(1, max_attempts + 1):
            result["attempts"] = attempt
            started = time.perf_counter()
            try:
                image_url = storage.signed_image_url(reference["image_path"], expires_in=900)
                if not image_url or not image_url.startswith("https://"):
                    raise RuntimeError("Signed image unavailable")
                preprocessing = candidate.get("image_preprocessing") or {}
                request_image, image_audit = _resized_image_input(
                    image_url,
                    max_dimension=int(preprocessing.get("max_dimension") or 0),
                    client=endpoint.client,
                    timeout=timeout,
                )
                payload, text = endpoint.request(
                    model=candidate["model"], prompt=prompt,
                    image_url=request_image, detail=candidate["detail"],
                    max_tokens=int(candidate.get("output_max_tokens") or 0),
                    schema=output_schema,
                )
                result.update(
                    usage=_usage(payload), image_preprocessing=image_audit,
                    raw_response_payload=_redact_request_image(payload, request_image, image_url),
                    raw_response_text=_redact_request_image(text, request_image, image_url),
                )
                cleaned_text = _clean_response_text(text)
                result["cleaned_response_text"] = _redact_request_image(
                    cleaned_text, request_image, image_url,
                )
                result["response_text"] = result["cleaned_response_text"]
                try:
                    syntax_payload = json.loads(cleaned_text)
                    if isinstance(syntax_payload, dict):
                        result["syntax_prediction"] = _redact_request_image(
                            _coerce_prediction_scalars(syntax_payload),
                            request_image,
                            image_url,
                        )
                except json.JSONDecodeError:
                    pass
                raw_prediction, _, diagnostic_repairs, raw_contract_valid = (
                    _schema_prediction_with_local_repairs(
                        cleaned_text,
                        taxonomy=taxonomy["recognition_taxonomy"],
                    )
                )
                result["raw_prediction"] = _redact_request_image(
                    raw_prediction, request_image, image_url,
                )
                result["raw_contract_valid"] = raw_contract_valid
                result["text_repair_actions"] = diagnostic_repairs
                parsed_candidate, parsed_text, repair_actions, raw_contract_valid = (
                    _parse_with_local_repairs(
                        cleaned_text,
                        taxonomy=taxonomy["recognition_taxonomy"],
                    )
                )
                result["raw_contract_valid"] = raw_contract_valid
                result["text_repair_actions"] = repair_actions
                if repair_actions:
                    result["repaired_response_text"] = _redact_request_image(
                        parsed_text, request_image, image_url,
                    )
                parsed = parsed_candidate.candidate.model_dump()
                result["formatting_repaired"] = (
                    parsed_candidate.formatting_repaired or bool(repair_actions)
                )
                result["raw_prediction"] = _redact_request_image(parsed, request_image, image_url)
                normalization_input = parsed
                result["normalization_input"] = _redact_request_image(
                    normalization_input, request_image, image_url,
                )
                normalized = service._normalize_model_payload(
                    normalization_input, raw_response={},
                    allowed_categories=taxonomy["allowed_categories"],
                    allowed_taxonomy=taxonomy["allowed_taxonomy"],
                )
                result.update(
                    status="succeeded", latency_seconds=round(time.perf_counter() - started, 6),
                    normalized_prediction=_redact_request_image(
                        normalized.model_dump(), request_image, image_url,
                    ),
                    completed_at=utc_now(),
                )
                result.pop("error", None)
                break
            except Exception as error:
                result.update(
                    status="failed", latency_seconds=round(time.perf_counter() - started, 6),
                    error=_safe_error(error), completed_at=utc_now(),
                )
                if isinstance(error, ShadowHTTPError):
                    result["raw_error_response"] = _redact_request_image(
                        error.payload,
                        locals().get("request_image", ""),
                        locals().get("image_url", ""),
                    )
                    if error.status_code in {401, 403} or error.code in {
                        "credit_balance_exhausted", "insufficient_quota", "invalid_api_key",
                        "billing_hard_limit_reached",
                    }:
                        blocked_reason = f"provider_{error.status_code}:{error.code}"
                if attempt < max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))
        write_json_atomic(result_path, result)
        if result.get("usage") is not None:
            spent += _estimated_usage_cost(result["usage"], pricing)
        processed += 1
        if blocked_reason:
            break
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    summary = summarize_run(run_dir)
    remaining = len(references) - len(list((run_dir / "results").glob("*.json")))
    manifest.update(
        state="blocked" if blocked_reason else ("complete" if remaining == 0 else "partial"),
        blocked_reason=blocked_reason,
        updated_at=utc_now(), completed_at=utc_now() if remaining == 0 else None,
        result_count=len(references) - remaining,
        budget_usd=budget_usd,
        estimated_spend_usd=spent,
    )
    write_json_atomic(manifest_path, manifest)
    return summary


def reparse_results(run_dir: Path) -> dict[str, Any]:
    """Re-evaluate stored provider text without network or model calls."""
    taxonomy = read_json(run_dir / "taxonomy.json")
    service = ClothingRecognitionService()
    changed = 0
    for result_path in sorted((run_dir / "results").glob("*.json")):
        result = read_json(result_path)
        cleaned_text = result.get("cleaned_response_text")
        if not cleaned_text:
            continue
        syntax_changed = False
        try:
            syntax_payload = json.loads(cleaned_text)
            if isinstance(syntax_payload, dict):
                result["syntax_prediction"] = _coerce_prediction_scalars(syntax_payload)
                syntax_changed = True
        except json.JSONDecodeError:
            pass
        if result.get("status") != "failed":
            write_json_atomic(result_path, result)
            continue
        diagnostic_changed = False
        try:
            raw_prediction, repaired_text, repair_actions, raw_contract_valid = (
                _schema_prediction_with_local_repairs(
                    result["cleaned_response_text"],
                    taxonomy=taxonomy["recognition_taxonomy"],
                )
            )
            result.update(
                raw_prediction=raw_prediction,
                raw_contract_valid=raw_contract_valid,
                text_repair_actions=repair_actions,
                repaired_response_text=repaired_text if repair_actions else None,
            )
            diagnostic_changed = True
        except Exception:
            pass
        try:
            parsed_candidate, parsed_text, repair_actions, raw_contract_valid = (
                _parse_with_local_repairs(
                    result["cleaned_response_text"],
                    taxonomy=taxonomy["recognition_taxonomy"],
                )
            )
            parsed = parsed_candidate.candidate.model_dump()
            normalized = service._normalize_model_payload(
                parsed,
                raw_response={},
                allowed_categories=taxonomy["allowed_categories"],
                allowed_taxonomy=taxonomy["allowed_taxonomy"],
            )
        except Exception:
            if diagnostic_changed or syntax_changed:
                write_json_atomic(result_path, result)
            continue
        result["original_error"] = result.pop("error", None)
        result.update(
            status="succeeded",
            raw_contract_valid=raw_contract_valid,
            text_repair_actions=repair_actions,
            repaired_response_text=parsed_text if repair_actions else None,
            formatting_repaired=(
                parsed_candidate.formatting_repaired or bool(repair_actions)
            ),
            raw_prediction=parsed,
            normalization_input=parsed,
            normalized_prediction=normalized.model_dump(),
            reparsed_at=utc_now(),
        )
        write_json_atomic(result_path, result)
        changed += 1
    summary = summarize_run(run_dir)
    summary["offline_reparse"] = {"changed_results": changed}
    write_json_atomic(run_dir / "summary.json", summary)
    return summary


def _tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    values = value if isinstance(value, list) else re.split(r"\s*,\s*", str(value))
    return {str(item).strip().casefold() for item in values if str(item).strip()}


def _candidate_value(prediction: dict[str, Any], field: str) -> Any:
    return prediction.get("seasons") if field == "season" else prediction.get(field)


def _equal(reference: Any, candidate: Any, field: str) -> bool:
    if field in SET_FIELDS:
        return _tokens(reference) == _tokens(candidate)
    if isinstance(reference, str) or isinstance(candidate, str):
        return str(reference or "").strip().casefold() == str(candidate or "").strip().casefold()
    return reference == candidate


def _field_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    result = {}
    for field in REFERENCE_FIELDS:
        eligible = [(ref[field], _candidate_value(pred, field)) for ref, pred in pairs if field in ref]
        correct = sum(_equal(reference, candidate, field) for reference, candidate in eligible)
        result[field] = {
            "correct": correct,
            "total": len(eligible),
            "accuracy": correct / len(eligible) if eligible else None,
        }
    return result


def _agreement_summary(
    description: str, pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "description": description,
        "items": len(pairs),
        "fields": _field_metrics(pairs),
        "category_macro_f1": _macro_f1(pairs, "category"),
        "subtype_macro_f1": _macro_f1(pairs, "subtype"),
        "multilabel": {field: _multilabel_f1(pairs, field) for field in SET_FIELDS},
    }


def _macro_f1(pairs: list[tuple[dict[str, Any], dict[str, Any]]], field: str) -> float | None:
    eligible = [(str(ref[field]), str(_candidate_value(pred, field) or "")) for ref, pred in pairs if ref.get(field)]
    labels = sorted({reference for reference, _ in eligible})
    if not labels:
        return None
    scores = []
    for label in labels:
        tp = sum(reference == label and candidate == label for reference, candidate in eligible)
        fp = sum(reference != label and candidate == label for reference, candidate in eligible)
        fn = sum(reference == label and candidate != label for reference, candidate in eligible)
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    return sum(scores) / len(scores)


def _multilabel_f1(pairs: list[tuple[dict[str, Any], dict[str, Any]]], field: str) -> dict[str, Any]:
    tp = fp = fn = 0
    total = 0
    for reference, prediction in pairs:
        if field not in reference:
            continue
        expected, actual = _tokens(reference[field]), _tokens(_candidate_value(prediction, field))
        tp += len(expected & actual)
        fp += len(actual - expected)
        fn += len(expected - actual)
        total += 1
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return {"items": total, "precision": precision, "recall": recall, "f1": f1}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def summarize_run(run_dir: Path) -> dict[str, Any]:
    references = read_json(run_dir / "references.json")
    results = {path.stem: read_json(path) for path in (run_dir / "results").glob("*.json")}
    current_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    manual_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    raw_current_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    raw_manual_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    syntax_current_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    syntax_manual_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rows = []
    for reference in references:
        result = results.get(reference["item_id"])
        prediction = (result or {}).get("normalized_prediction")
        raw_prediction = (result or {}).get("raw_prediction")
        syntax_prediction = (result or {}).get("syntax_prediction")
        if prediction:
            current_pairs.append((reference["production"], prediction))
            if reference.get("manual_confirmation"):
                manual_pairs.append((reference["manual_confirmation"], prediction))
        if raw_prediction:
            comparable_raw = _coerce_prediction_scalars(raw_prediction)
            raw_current_pairs.append((reference["production"], comparable_raw))
            if reference.get("manual_confirmation"):
                raw_manual_pairs.append((reference["manual_confirmation"], comparable_raw))
        if syntax_prediction:
            syntax_current_pairs.append((reference["production"], syntax_prediction))
            if reference.get("manual_confirmation"):
                syntax_manual_pairs.append(
                    (reference["manual_confirmation"], syntax_prediction)
                )
        row = {
            "item_id": reference["item_id"],
            "status": (result or {}).get("status", "pending"),
            "manual_reference": bool(reference.get("manual_confirmation")),
            "latency_seconds": (result or {}).get("latency_seconds"),
            "input_tokens": ((result or {}).get("usage") or {}).get("input_tokens"),
            "output_tokens": ((result or {}).get("usage") or {}).get("output_tokens"),
            "error_type": ((result or {}).get("error") or {}).get("type"),
        }
        for field in CORE_FIELDS:
            row[f"production_{field}"] = reference["production"].get(field)
            row[f"candidate_{field}"] = _candidate_value(prediction or {}, field)
            row[f"agrees_{field}"] = _equal(reference["production"].get(field), row[f"candidate_{field}"], field) if prediction else None
        rows.append(row)

    succeeded = [result for result in results.values() if result.get("status") == "succeeded"]
    model_calls = [
        result for result in results.values()
        if result.get("raw_response_payload") is not None or result.get("usage") is not None
    ]
    parsed = [result for result in results.values() if result.get("raw_prediction") is not None]
    syntax_parsed = [
        result for result in results.values()
        if result.get("syntax_prediction") is not None
    ]
    latencies = [
        float(result["latency_seconds"])
        for result in model_calls if result.get("latency_seconds") is not None
    ]
    usage_totals = {
        key: sum(int((result.get("usage") or {}).get(key) or 0) for result in model_calls)
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    pricing = ((manifest.get("candidate") or {}).get("pricing_usd_per_million") or {})
    estimated_cost = None
    if pricing.get("input") is not None and pricing.get("output") is not None:
        input_tokens = usage_totals["input_tokens"]
        cached_tokens = usage_totals["cached_input_tokens"]
        uncached_tokens = max(0, input_tokens - cached_tokens)
        cached_rate = pricing.get("cached_input")
        if cached_rate is None:
            cached_rate = pricing["input"]
        estimated_cost = (
            uncached_tokens * float(pricing["input"])
            + cached_tokens * float(cached_rate)
            + usage_totals["output_tokens"] * float(pricing["output"])
        ) / 1_000_000
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "items": {
            "prepared": len(references), "completed": len(results), "succeeded": len(succeeded),
            "failed": sum(result.get("status") == "failed" for result in results.values()),
            "pending": len(references) - len(results),
            "success_rate": len(succeeded) / len(results) if results else None,
            "model_call_succeeded": len(model_calls),
            "model_call_success_rate": len(model_calls) / len(results) if results else None,
            "json_parsed": len(parsed),
            "json_parse_rate": len(parsed) / len(model_calls) if model_calls else None,
            "json_syntax_valid": len(syntax_parsed),
            "json_syntax_valid_rate": (
                len(syntax_parsed) / len(model_calls) if model_calls else None
            ),
            "production_schema_valid": len(succeeded),
            "production_schema_valid_rate": len(succeeded) / len(parsed) if parsed else None,
        },
        "production_agreement": _agreement_summary(
            "Production-schema-valid candidate agreement with stored labels; not human ground truth.",
            current_pairs,
        ),
        "manual_ground_truth": _agreement_summary(
            "Production-schema-valid candidate agreement with item-card-confirmed labels.",
            manual_pairs,
        ),
        "raw_prediction_agreement": _agreement_summary(
            "Parsed raw prediction agreement before production-schema validation; diagnostic only.",
            raw_current_pairs,
        ),
        "raw_manual_ground_truth": _agreement_summary(
            "Parsed raw prediction agreement with confirmed labels before schema validation; diagnostic only.",
            raw_manual_pairs,
        ),
        "syntax_prediction_agreement": _agreement_summary(
            "Syntactically valid JSON agreement before schema or semantic validation; diagnostic only.",
            syntax_current_pairs,
        ),
        "syntax_manual_ground_truth": _agreement_summary(
            "Syntactically valid JSON agreement with confirmed labels before schema or semantic validation; diagnostic only.",
            syntax_manual_pairs,
        ),
        "performance": {
            "latency_seconds": {
                "mean": statistics.fmean(latencies) if latencies else None,
                "p50": statistics.median(latencies) if latencies else None,
                "p95": _percentile(latencies, 0.95),
            },
            "usage_totals": usage_totals,
            "pricing_usd_per_million": pricing or None,
            "estimated_cost_usd": estimated_cost,
        },
    }
    write_json_atomic(run_dir / "summary.json", summary)
    fields = list(rows[0]) if rows else ["item_id", "status"]
    temporary = run_dir / ".results.csv.tmp"
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(run_dir / "results.csv")
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Freeze references without calling a model")
    prepare.add_argument("--user-id", required=True)
    prepare.add_argument("--model", required=True)
    prepare.add_argument("--base-url", required=True)
    prepare.add_argument(
        "--protocol",
        choices=("responses", "chat-completions", "gemini-generate-content"),
        default="chat-completions",
    )
    prepare.add_argument("--detail", choices=("low", "high", "auto"), default="low")
    prepare.add_argument(
        "--response-format", choices=(STRICT_RESPONSE_FORMAT,),
        default=STRICT_RESPONSE_FORMAT,
        help="Strict JSON Schema is mandatory for comparable shadow evaluations",
    )
    prepare.add_argument("--model-revision")
    prepare.add_argument("--deployment-label")
    prepare.add_argument("--input-usd-per-million", type=float)
    prepare.add_argument("--cached-input-usd-per-million", type=float)
    prepare.add_argument("--output-usd-per-million", type=float)
    prepare.add_argument(
        "--image-max-dimension", type=int, default=0,
        help="Resize images in memory to fit this dimension before local inference; 0 disables",
    )
    prepare.add_argument(
        "--output-max-tokens", type=int, default=0,
        help="Candidate output token cap recorded in the run manifest; 0 uses provider default",
    )
    prepare.add_argument("--limit", type=int, default=10, help="0 means all eligible garments")
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    prepare.add_argument("--baseline", help="Path or ID of the recovery baseline used for this experiment")

    run = commands.add_parser("run", help="Run or resume candidate inference")
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--api-key-env", default="SHADOW_AI_API_KEY")
    run.add_argument("--allow-no-api-key", action="store_true", help="Only for a trusted local endpoint")
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("--max-items", type=int, default=0, help="0 means all remaining prepared items")
    run.add_argument("--max-attempts", type=int, default=1)
    run.add_argument("--delay-seconds", type=float, default=0)
    run.add_argument("--retry-failures", action="store_true")
    run.add_argument("--budget-usd", type=float, default=10.0)

    summarize = commands.add_parser("summarize", help="Rebuild metrics without model calls")
    summarize.add_argument("--run-dir", type=Path, required=True)
    reparse = commands.add_parser(
        "reparse", help="Apply approved deterministic repairs to stored responses",
    )
    reparse.add_argument("--run-dir", type=Path, required=True)
    clone = commands.add_parser("clone", help="Clone byte-identical frozen inputs for another model")
    clone.add_argument("--source-run", type=Path, required=True)
    clone.add_argument("--model", required=True)
    clone.add_argument("--base-url", required=True)
    clone.add_argument(
        "--protocol",
        choices=("responses", "chat-completions", "gemini-generate-content"),
        required=True,
    )
    clone.add_argument(
        "--response-format", choices=(STRICT_RESPONSE_FORMAT,),
        default=STRICT_RESPONSE_FORMAT,
        help="Strict JSON Schema is mandatory for comparable shadow evaluations",
    )
    clone.add_argument("--model-revision")
    clone.add_argument("--deployment-label")
    clone.add_argument("--prompt-variant")
    clone.add_argument(
        "--prompt-suffix-file", type=Path,
        help="Append a versioned provider-specific instruction block to the frozen prompt",
    )
    clone.add_argument("--input-usd-per-million", type=float)
    clone.add_argument("--cached-input-usd-per-million", type=float)
    clone.add_argument("--output-usd-per-million", type=float)
    clone.add_argument("--output-max-tokens", type=int, default=1800)
    clone.add_argument(
        "--image-max-dimension", type=int,
        help="Override the source run's image resize dimension; omit to inherit",
    )
    clone.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "prepare":
        run_dir = prepare_run(
            user_id=args.user_id, model=args.model, base_url=args.base_url,
            protocol=args.protocol, detail=args.detail, limit=args.limit,
            output_root=args.output_root, baseline=args.baseline,
            response_format=args.response_format,
            model_revision=args.model_revision, deployment_label=args.deployment_label,
            input_usd_per_million=args.input_usd_per_million,
            cached_input_usd_per_million=args.cached_input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
            image_max_dimension=args.image_max_dimension,
            output_max_tokens=args.output_max_tokens,
        )
        print(json.dumps({"state": "prepared", "run_dir": str(run_dir)}, indent=2))
    elif args.command == "run":
        summary = run_shadow(
            args.run_dir.resolve(), api_key_env=args.api_key_env, timeout=args.timeout,
            max_items=args.max_items, max_attempts=args.max_attempts,
            delay_seconds=args.delay_seconds, retry_failures=args.retry_failures,
            budget_usd=args.budget_usd,
            allow_no_api_key=args.allow_no_api_key,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    elif args.command == "clone":
        run_dir = clone_run(
            source_run=args.source_run.resolve(), model=args.model, base_url=args.base_url,
            protocol=args.protocol, response_format=args.response_format,
            output_root=args.output_root, model_revision=args.model_revision,
            deployment_label=args.deployment_label,
            input_usd_per_million=args.input_usd_per_million,
            cached_input_usd_per_million=args.cached_input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
            output_max_tokens=args.output_max_tokens,
            image_max_dimension=args.image_max_dimension,
            prompt_suffix=(
                args.prompt_suffix_file.read_text(encoding="utf-8")
                if args.prompt_suffix_file else None
            ),
            prompt_variant=args.prompt_variant,
        )
        print(json.dumps({"state": "prepared", "run_dir": str(run_dir)}, indent=2))
    elif args.command == "reparse":
        print(json.dumps(reparse_results(args.run_dir.resolve()), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summarize_run(args.run_dir.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
