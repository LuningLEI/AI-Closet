"""Parsing, safe formatting repair and classified output failures."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from app.ai.gateway import AIResult
from app.models.recognition_output import RecognitionCandidateV1, validate_candidate_taxonomy


class RecognitionFailureKind(StrEnum):
    EMPTY = "empty_response"
    TRUNCATED = "truncated_response"
    JSON_SYNTAX = "invalid_json"
    SCHEMA = "schema_violation"
    SEMANTIC = "semantic_violation"
    REWRITE_FAILED = "text_rewrite_failed"
    TARGETED_RETRY_FAILED = "targeted_retry_failed"


class RecognitionOutputError(ValueError):
    kind: RecognitionFailureKind
    retry_requires_vision: bool = False

    def __init__(self, message: str, *, issues: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class EmptyRecognitionResponse(RecognitionOutputError):
    kind = RecognitionFailureKind.EMPTY
    retry_requires_vision = True


class TruncatedRecognitionResponse(RecognitionOutputError):
    kind = RecognitionFailureKind.TRUNCATED
    retry_requires_vision = True


class RecognitionJSONSyntaxError(RecognitionOutputError):
    kind = RecognitionFailureKind.JSON_SYNTAX
    retry_requires_vision = False


class RecognitionSchemaError(RecognitionOutputError):
    kind = RecognitionFailureKind.SCHEMA
    retry_requires_vision = False


class RecognitionSemanticError(RecognitionOutputError):
    kind = RecognitionFailureKind.SEMANTIC
    retry_requires_vision = False


class RecognitionRewriteFailed(RecognitionOutputError):
    kind = RecognitionFailureKind.REWRITE_FAILED
    retry_requires_vision = False


class TargetedRecognitionRetryFailed(RecognitionOutputError):
    kind = RecognitionFailureKind.TARGETED_RETRY_FAILED
    retry_requires_vision = False


@dataclass(frozen=True)
class ParsedRecognitionCandidate:
    candidate: RecognitionCandidateV1
    formatting_repaired: bool
    repair_actions: tuple[str, ...] = ()


_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.IGNORECASE | re.DOTALL)
_TERMINAL_TOKENS = ("<|im_end|>", "<|endoftext|>")
_SAFE_SUBTYPE_ALIASES = {
    ("shoes", "boot"): "Boots",
}


def repair_recognition_payload(
    payload: dict[str, Any],
    *,
    taxonomy: dict[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Normalize equivalent provider shapes without inferring garment semantics."""

    repaired = dict(payload)
    actions: list[str] = []
    for field in ("category", "subcategory", "subtype"):
        value = repaired.get(field)
        if isinstance(value, list):
            repaired[field] = next(
                (str(item).strip() for item in value if str(item).strip()),
                None,
            )
            actions.append(f"scalarize_{field}")

    category = repaired.get("category")
    subtype = repaired.get("subtype")
    if isinstance(category, str) and isinstance(subtype, str):
        alias = _SAFE_SUBTYPE_ALIASES.get(
            (category.strip().casefold(), subtype.strip().casefold())
        )
        subtype_catalog = taxonomy.get("subtypes")
        allowed = subtype_catalog.get(category) if isinstance(subtype_catalog, dict) else None
        if alias and allowed is not None and alias in allowed:
            repaired["subtype"] = alias
            actions.append(f"normalize_subtype_alias:{subtype}->{alias}")
        elif allowed is not None and subtype not in allowed:
            # The provider schema constrains subtypes globally, but portable JSON
            # Schema cannot express the category/subtype dependency.  Null is a
            # safer representation than inventing a category-specific subtype.
            repaired["subtype"] = None
            actions.append(f"drop_category_incompatible_subtype:{subtype}")

    occasion_scores = repaired.get("occasion_scores")
    if isinstance(occasion_scores, dict):
        repaired["occasion_scores"] = [
            {"occasion": str(occasion), "score": score}
            for occasion, score in occasion_scores.items()
        ]
        actions.append("reshape_occasion_scores")

    if "warnings" not in repaired:
        repaired["warnings"] = []
        actions.append("default_empty_warnings")

    wearing_profile = repaired.get("wearing_profile")
    if isinstance(wearing_profile, dict) and "requires_inner_layer" not in wearing_profile:
        repaired["wearing_profile"] = {
            **wearing_profile,
            "requires_inner_layer": None,
        }
        actions.append("default_requires_inner_layer_null")

    color = repaired.get("color")
    color_tones = repaired.get("color_tones")
    if (
        isinstance(color, str)
        and color.strip().casefold() == "multicolor"
        and isinstance(color_tones, list)
    ):
        allowed_colors = set(taxonomy.get("colors") or [])
        tone_colors = list(dict.fromkeys(
            str(tone.get("color") or "").strip()
            for tone in color_tones if isinstance(tone, dict)
        ))
        if tone_colors and all(value in allowed_colors for value in tone_colors):
            repaired["color"] = ", ".join(tone_colors)
            actions.append("expand_multicolor_from_color_tones")

    color = repaired.get("color")
    color_tones = repaired.get("color_tones")
    if isinstance(color, str) and isinstance(color_tones, list):
        declared = {value.strip() for value in color.split(",") if value.strip()}
        compatible_tones = [
            tone for tone in color_tones
            if isinstance(tone, dict) and str(tone.get("color") or "").strip() in declared
        ]
        if len(compatible_tones) != len(color_tones):
            # Keep the user-facing primary color and discard contradictory
            # auxiliary estimates.  No new visual fact is introduced.
            repaired["color_tones"] = compatible_tones
            actions.append("drop_color_tones_outside_primary_color")

    wearing_profile = repaired.get("wearing_profile")
    if isinstance(wearing_profile, dict) and isinstance(wearing_profile.get("wearing_modes"), list):
        profile = dict(wearing_profile)
        modes = list(dict.fromkeys(profile["wearing_modes"]))
        incompatible: set[str] = set()
        if profile.get("can_wear_alone") is False or profile.get("requires_inner_layer") is True:
            incompatible.add("standalone")
        if profile.get("can_layer_under") is False:
            incompatible.add("inner_layer")
        if profile.get("can_layer_over") is False:
            incompatible.update({"outer_layer_closed", "outer_layer_open"})
        if profile.get("closure_type") == "pullover":
            incompatible.add("outer_layer_open")
        filtered = [mode for mode in modes if mode not in incompatible]
        if filtered != profile["wearing_modes"]:
            profile["wearing_modes"] = filtered
            repaired["wearing_profile"] = profile
            actions.append("drop_modes_contradicting_capabilities")

    seasons = repaired.get("seasons")
    if isinstance(seasons, list) and any(
        str(value).strip().casefold() == "all-season" for value in seasons
    ):
        explicit = [
            value for value in seasons
            if str(value).strip().casefold() != "all-season"
        ]
        repaired["seasons"] = list(dict.fromkeys([
            *explicit,
            *list(taxonomy.get("seasons") or []),
        ]))
        actions.append("expand_legacy_all_season")

    return repaired, tuple(actions)


def _response_is_truncated(payload: dict[str, Any]) -> bool:
    if payload.get("status") == "incomplete":
        return True
    details = payload.get("incomplete_details")
    if isinstance(details, dict) and details.get("reason") in {"max_output_tokens", "length"}:
        return True
    if payload.get("finish_reason") in {"length", "max_tokens"}:
        return True
    for choice in payload.get("choices", []):
        if isinstance(choice, dict) and choice.get("finish_reason") in {"length", "max_tokens"}:
            return True
    return False


def _strip_provider_wrappers(text: str) -> str:
    cleaned = text.lstrip("\ufeff").strip()
    while any(cleaned.endswith(token) for token in _TERMINAL_TOKENS):
        for token in _TERMINAL_TOKENS:
            if cleaned.endswith(token):
                cleaned = cleaned[: -len(token)].rstrip()
                break
    match = _FENCE.fullmatch(cleaned)
    return match.group(1).strip() if match else cleaned


def _extract_single_json_object(text: str) -> dict[str, Any] | None:
    """Extract one intact object without changing any byte inside that object."""

    start = text.find("{")
    if start < 0:
        return None
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    suffix = text[start + end :].strip()
    if suffix and ("{" in suffix or "[" in suffix):
        return None
    return value


def _looks_truncated(text: str) -> bool:
    stripped = text.rstrip()
    in_string = False
    escaped = False
    braces = brackets = 0
    for character in stripped:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            braces += 1
        elif character == "}":
            braces -= 1
        elif character == "[":
            brackets += 1
        elif character == "]":
            brackets -= 1
    return in_string or braces > 0 or brackets > 0


def parse_recognition_candidate(
    result: AIResult,
    *,
    taxonomy: dict[str, Any],
) -> ParsedRecognitionCandidate:
    text = result.text
    if not text.strip():
        if _response_is_truncated(result.payload):
            raise TruncatedRecognitionResponse("Recognition response ended before output text was produced")
        raise EmptyRecognitionResponse("Recognition response did not include output text")

    cleaned = _strip_provider_wrappers(text)
    repaired = cleaned != text.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as first_error:
        extracted = _extract_single_json_object(cleaned)
        if extracted is not None:
            parsed = extracted
            repaired = True
        elif _response_is_truncated(result.payload) or _looks_truncated(cleaned):
            raise TruncatedRecognitionResponse("Recognition response was truncated") from first_error
        else:
            raise RecognitionJSONSyntaxError("Recognition response was not valid JSON") from first_error

    if not isinstance(parsed, dict):
        raise RecognitionSchemaError("Recognition response must be one JSON object")
    parsed, repair_actions = repair_recognition_payload(parsed, taxonomy=taxonomy)
    repaired = repaired or bool(repair_actions)
    try:
        candidate = RecognitionCandidateV1.model_validate(parsed)
    except ValidationError as exc:
        issues = [
            {
                "path": ".".join(str(part) for part in issue.get("loc", ())),
                "code": str(issue.get("type") or "schema_violation"),
                "message": str(issue.get("msg") or "Schema validation failed")[:300],
            }
            for issue in exc.errors(include_url=False, include_input=False)
        ]
        raise RecognitionSchemaError(
            f"Recognition response failed schema validation: {exc}", issues=issues,
        ) from exc
    try:
        validate_candidate_taxonomy(candidate, taxonomy)
    except ValueError as exc:
        raise RecognitionSemanticError(
            f"Recognition response failed semantic validation: {exc}",
            issues=[{"path": "taxonomy", "code": "semantic_violation", "message": str(exc)[:300]}],
        ) from exc
    return ParsedRecognitionCandidate(
        candidate=candidate,
        formatting_repaired=repaired,
        repair_actions=repair_actions,
    )
