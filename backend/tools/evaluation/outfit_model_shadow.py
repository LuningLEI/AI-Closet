"""Paired, read-only outfit-generation evaluation across VLM providers.

The suite freezes anchors, production-selected candidate catalogs, prompts and
item revisions once.  Model runs consume that exact suite, write local audit
artifacts, and validate proposals with the production structural rules.  No
outfit, job, feedback, preference or taste table is modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.ai.gateway import OpenAIChatCompletionsGateway, OpenAICompatibleGateway
from app.models.domain import ClothingItemRecord
from app.outfits.catalog import exclusion_reason, rank_score
from app.outfits.compatibility import compatibility_issues
from app.outfits.compatibility import athletic, slot
from app.outfits.config import load_config
from app.outfits.diagnostics import OutfitModelError
from app.outfits.footwear import clothing_catalog
from app.outfits.models import Proposals
from app.outfits.service import automatic_anchor, ready, structural_rejection_codes
from app.outfits.store import build_store
from app.repositories.factory import build_closet_repository
from app.services.layering_fit import assess_outfit_layering
from app.services.storage_service import StorageService
from app.services.taste_profile_service import TasteProfileService
from app.services.taste_profile import item_taste_score
from tools.evaluation.paths import evaluation_path
from tools.evaluation.recognition_shadow import _redact_url, digest, write_json_atomic


SCHEMA_VERSION = "outfit-model-shadow-v1"
STRICT_SCHEMA_MODE = "json-schema"
DEFAULT_ROOT = evaluation_path("model_migration", "outfit_shadow")
INPUT_MODES = ("metadata-only", "metadata-and-images")
BOTTOM_TOP_TARGET = 12
BOTTOM_TOP_MAXIMUM = 15
BOTTOM_OUTERWEAR_MAXIMUM = 8
ITEM_FIELDS = (
    "id", "user_id", "image_url", "image_path", "category", "subtype", "color", "season",
    "style", "occasion", "material", "pattern", "fit", "length", "sleeve_length", "neckline",
    "layering_role", "wearing_profile", "color_tones", "warmth_level", "formality_score",
    "recognition_status", "recognition_source", "semantic_vector", "feature_vector", "metadata",
    "created_at", "updated_at",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _item_document(item: ClothingItemRecord) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    return {field: payload.get(field) for field in ITEM_FIELDS}


def _balanced_anchors(items: list[ClothingItemRecord], limit: int) -> list[ClothingItemRecord]:
    groups: dict[str, list[ClothingItemRecord]] = {}
    for item in sorted(items, key=lambda value: value.id):
        groups.setdefault(item.category, []).append(item)
    selected: list[ClothingItemRecord] = []
    while len(selected) < min(limit, len(items)):
        progressed = False
        for category in sorted(groups):
            if groups[category] and len(selected) < limit:
                selected.append(groups[category].pop(0))
                progressed = True
        if not progressed:
            break
    return selected


def _generation_prompt(prompt: str, input_mode: str) -> str:
    if input_mode not in INPUT_MODES:
        raise ValueError(f"Unsupported outfit shadow input mode: {input_mode}")
    candidate_policy = """

SHADOW CANDIDATE-POLICY EXPERIMENT:
- For a Bottoms anchor, first form a complete base with exactly one independently wearable base Top.
- A second Tops-slot garment is an optional upper layer, not another required core piece. Include it only when it has a clear, non-redundant layering purpose and is physically compatible.
- Across a batch for one Bottoms anchor, return at most two layered proposals containing two Tops-slot garments. Keep the other proposals single-top bases.
- For an Activewear Bottoms anchor, prefer supplied Activewear and genuinely sport-compatible tops before general casual tops. Do not use a formal blouse or statement top merely because its vector or color is close.
"""
    if input_mode == "metadata-and-images":
        return f"{prompt.rstrip()}{candidate_policy}"
    return f"""{prompt.rstrip()}

METADATA-ONLY EVALUATION MODE:
- No garment images are supplied in this generation stage. Use only the supplied item IDs and structured metadata.
- Ignore earlier wording that asks you to inspect images or visible details. Never claim to have visually inspected an item.
- Treat category, subtype, color, fit, length, warmth, formality and wearing_profile as fallible structured evidence.
- Enforce structural, layering, thermal and purpose constraints from those fields. If the metadata cannot support a safe combination, return fewer proposals.
- Use only supplied IDs. Do not invent garments, IDs, visual properties, shoes or accessories.
{candidate_policy}"""


def _ranked_evaluation_candidates(anchor, items, config, taste_profile):
    """Production-compatible filtering/ranking before experimental quotas."""
    garments = [item for item in items if slot(item) != "Shoes"]
    if config.accessory_pipeline:
        garments = [
            item for item in garments
            if slot(item) != "Accessories" or item.subtype == "Tights"
        ]
    candidates = [
        item for item in garments
        if item.id != anchor.id and not exclusion_reason(anchor, item, config)
    ]
    candidates.sort(key=lambda item: (
        -(rank_score(anchor, item, config) + 0.08 * item_taste_score(item, taste_profile)),
        digest([anchor.id, item.id]),
    ))
    return candidates


def _bottom_evaluation_catalog(anchor, items, config, taste_profile, limit):
    """Bound Top dominance and preserve athletic-purpose candidates for shadow tests."""
    ranked = _ranked_evaluation_candidates(anchor, items, config, taste_profile)
    tops = [item for item in ranked if slot(item) == "Tops"]
    outerwear = [item for item in ranked if slot(item) == "Outerwear"]
    active_anchor = athletic(anchor)
    if active_anchor:
        tops = [item for item in tops if athletic(item)] + [
            item for item in tops if not athletic(item)
        ]
        outerwear = [item for item in outerwear if athletic(item)] + [
            item for item in outerwear if not athletic(item)
        ]

    active_top_count = sum(athletic(item) for item in tops) if active_anchor else 0
    top_limit = min(
        BOTTOM_TOP_MAXIMUM,
        max(BOTTOM_TOP_TARGET, active_top_count),
    )
    selected = [anchor, *tops[:top_limit], *outerwear[:BOTTOM_OUTERWEAR_MAXIMUM]]
    selected_ids = {item.id for item in selected}
    remaining = defaultdict(list)
    for item in ranked:
        role = slot(item)
        if item.id not in selected_ids and role not in {"Tops", "Outerwear"}:
            remaining[role].append(item)
    while len(selected) < limit and any(remaining.values()):
        for role in sorted(remaining):
            if remaining[role] and len(selected) < limit:
                item = remaining[role].pop(0)
                selected.append(item)
                selected_ids.add(item.id)
    return selected[:limit]


def _evaluation_catalog(anchor, items, config, taste_profile, limit):
    if slot(anchor) == "Bottoms":
        return _bottom_evaluation_catalog(
            anchor, items, config, taste_profile, limit,
        )
    catalog = clothing_catalog(anchor, items, config, taste_profile)
    return catalog[:limit]


def prepare_suite(
    *, user_id: str, scenarios: int, output_root: Path, catalog_limit: int = 0,
    input_mode: str = "metadata-and-images",
) -> Path:
    if scenarios < 1:
        raise ValueError("scenarios must be positive")
    if catalog_limit < 0:
        raise ValueError("catalog_limit must be zero (production default) or positive")
    if input_mode not in INPUT_MODES:
        raise ValueError(f"Unsupported outfit shadow input mode: {input_mode}")
    repository = build_closet_repository()
    read = getattr(repository, "list_items_for_outfit_candidates", repository.list_items_for_outfits)
    items = [item for item in read(user_id) if item.user_id == user_id and ready(item)]
    anchors = _balanced_anchors([item for item in items if automatic_anchor(item)], scenarios)
    if not anchors:
        raise RuntimeError("No eligible outfit anchors were found")
    config = load_config()
    # Shadow preparation is read-only. Use the last persisted projection instead
    # of invoking ensure_current(), which may materialize a newer production row.
    taste = TasteProfileService(build_store(repository)).get(user_id)
    frozen_items: dict[str, dict[str, Any]] = {}
    rows = []
    for index, anchor in enumerate(anchors, start=1):
        # Evaluate the exact production clothing-generation stage. Shoes and
        # ordinary accessories are selected by the later batched accessory
        # stage and must not appear in this model's candidate catalog.
        effective_limit = catalog_limit or config.catalog_limit
        catalog = _evaluation_catalog(anchor, items, config, taste, effective_limit)
        for item in catalog:
            frozen_items[item.id] = _item_document(item)
        rows.append({
            "scenario_id": f"S{index:03d}",
            "anchor_item_id": anchor.id,
            "catalog_item_ids": [item.id for item in catalog],
            "request": {
                "anchor_item_id": anchor.id,
                "maximum_outfits": config.candidates_per_anchor,
                "maximum_items_per_outfit": config.max_items_per_outfit - 1,
                "learned_taste": None,
            },
        })
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    prompt = _generation_prompt(config.clothing_text, input_mode)
    (suite_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(suite_dir / "items.json", frozen_items)
    write_json_atomic(suite_dir / "scenarios.json", rows)
    write_json_atomic(suite_dir / "output_schema.json", Proposals.model_json_schema())
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "user_id": user_id,
        "scenario_count": len(rows),
        "item_count": len(frozen_items),
        "catalog_limit": catalog_limit or config.catalog_limit,
        "catalog_limit_mode": "evaluation_override" if catalog_limit else "production_default",
        "candidate_policy": {
            "name": "bottom-purpose-balanced-v1",
            "scope": "shadow_evaluation_only",
            "bottom_top_target": BOTTOM_TOP_TARGET,
            "bottom_top_maximum": BOTTOM_TOP_MAXIMUM,
            "bottom_outerwear_maximum": BOTTOM_OUTERWEAR_MAXIMUM,
            "activewear_bottom_priority": "activewear_tops_then_general_tops",
            "maximum_layered_top_proposals": 2,
            "allow_underfilled_catalog": True,
        },
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "input_mode": input_mode,
        "items_sha256": digest(frozen_items),
        "scenarios_sha256": digest(rows),
        "output_schema_sha256": digest(Proposals.model_json_schema()),
        "policy": {
            "require_shoes": config.require_shoes,
            "max_items_per_outfit": config.max_items_per_outfit,
            "compatibility_rules": config.compatibility_rules.model_dump(),
            "layering_fit_policy": config.layering_fit_policy.model_dump(),
        },
        "safety": {"production_writes": False, "signed_url_ttl_seconds": 900},
    }
    write_json_atomic(suite_dir / "suite_manifest.json", manifest)
    return suite_dir


def derive_metadata_only_suite(*, source_suite: Path, output_root: Path) -> Path:
    """Reuse one frozen catalog while removing images from generation."""
    source_manifest = json.loads((source_suite / "suite_manifest.json").read_text())
    items_doc = json.loads((source_suite / "items.json").read_text())
    scenarios = json.loads((source_suite / "scenarios.json").read_text())
    schema = json.loads((source_suite / "output_schema.json").read_text())
    if digest(items_doc) != source_manifest["items_sha256"]:
        raise RuntimeError("Source outfit suite item checksum mismatch")
    if digest(scenarios) != source_manifest["scenarios_sha256"]:
        raise RuntimeError("Source outfit suite scenario checksum mismatch")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    prompt = _generation_prompt(load_config().clothing_text, "metadata-only")
    (suite_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(suite_dir / "items.json", items_doc)
    write_json_atomic(suite_dir / "scenarios.json", scenarios)
    write_json_atomic(suite_dir / "output_schema.json", schema)
    manifest = {
        **source_manifest,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "derived_from_suite": source_manifest["suite_id"],
        "input_mode": "metadata-only",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "items_sha256": digest(items_doc),
        "scenarios_sha256": digest(scenarios),
        "output_schema_sha256": digest(schema),
        "safety": {"production_writes": False, "signed_url_ttl_seconds": 900},
    }
    write_json_atomic(suite_dir / "suite_manifest.json", manifest)
    return suite_dir


def derive_rebalanced_suite(
    *, source_suite: Path, output_root: Path, catalog_limit: int = 30,
    input_mode: str = "metadata-only",
) -> Path:
    """Keep frozen anchors/items while applying the current shadow candidate policy."""
    if catalog_limit < 1:
        raise ValueError("catalog_limit must be positive")
    if input_mode not in INPUT_MODES:
        raise ValueError(f"Unsupported outfit shadow input mode: {input_mode}")
    source_manifest = json.loads((source_suite / "suite_manifest.json").read_text())
    items_doc = json.loads((source_suite / "items.json").read_text())
    source_scenarios = json.loads((source_suite / "scenarios.json").read_text())
    if digest(items_doc) != source_manifest["items_sha256"]:
        raise RuntimeError("Source outfit suite item checksum mismatch")
    if digest(source_scenarios) != source_manifest["scenarios_sha256"]:
        raise RuntimeError("Source outfit suite scenario checksum mismatch")

    items = [ClothingItemRecord.model_validate(row) for row in items_doc.values()]
    by_id = {item.id: item for item in items}
    config = load_config()
    scenarios = []
    selected_ids: set[str] = set()
    for source in source_scenarios:
        anchor = by_id.get(source["anchor_item_id"])
        if anchor is None:
            raise RuntimeError("Frozen anchor is absent from the source item universe")
        catalog = _evaluation_catalog(anchor, items, config, None, catalog_limit)
        selected_ids.update(item.id for item in catalog)
        scenarios.append({
            **source,
            "catalog_item_ids": [item.id for item in catalog],
            "request": {
                **source["request"],
                "maximum_outfits": config.candidates_per_anchor,
                "maximum_items_per_outfit": config.max_items_per_outfit - 1,
            },
        })

    frozen_items = {item_id: items_doc[item_id] for item_id in sorted(selected_ids)}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    prompt = _generation_prompt(config.clothing_text, input_mode)
    schema = Proposals.model_json_schema()
    (suite_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(suite_dir / "items.json", frozen_items)
    write_json_atomic(suite_dir / "scenarios.json", scenarios)
    write_json_atomic(suite_dir / "output_schema.json", schema)
    manifest = {
        **source_manifest,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "derived_from_suite": source_manifest["suite_id"],
        "input_mode": input_mode,
        "item_count": len(frozen_items),
        "catalog_limit": catalog_limit,
        "catalog_limit_mode": "evaluation_rebalanced_override",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "items_sha256": digest(frozen_items),
        "scenarios_sha256": digest(scenarios),
        "output_schema_sha256": digest(schema),
        "candidate_policy": {
            "name": "bottom-purpose-balanced-v1",
            "scope": "shadow_evaluation_only",
            "bottom_top_target": BOTTOM_TOP_TARGET,
            "bottom_top_maximum": BOTTOM_TOP_MAXIMUM,
            "bottom_outerwear_maximum": BOTTOM_OUTERWEAR_MAXIMUM,
            "activewear_bottom_priority": "activewear_tops_then_general_tops",
            "maximum_layered_top_proposals": 2,
            "allow_underfilled_catalog": True,
        },
        "safety": {"production_writes": False, "signed_url_ttl_seconds": 900},
    }
    write_json_atomic(suite_dir / "suite_manifest.json", manifest)
    return suite_dir


def _gateway(protocol: str, *, base_url: str, api_key: str, schema_mode: str):
    if schema_mode != STRICT_SCHEMA_MODE:
        raise ValueError(
            "Shadow model evaluations require strict JSON Schema; "
            "json-object and unstructured output are not allowed"
        )
    if protocol == "responses":
        return OpenAICompatibleGateway(api_key=api_key, base_url=base_url)
    return OpenAIChatCompletionsGateway(
        api_key=api_key, base_url=base_url, schema_mode=schema_mode,
    )


def _usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}
    return {
        "input_tokens": int(usage.get("input_tokens", usage.get("prompt_tokens")) or 0),
        "cached_input_tokens": int(details.get("cached_tokens", usage.get("cached_input_tokens")) or 0),
        "output_tokens": int(usage.get("output_tokens", usage.get("completion_tokens")) or 0),
    }


def _estimated_cost(usage: dict[str, int], rates: dict[str, float]) -> float:
    cached = usage["cached_input_tokens"]
    uncached = max(0, usage["input_tokens"] - cached)
    return (
        uncached * rates["input"] + cached * rates["cached_input"]
        + usage["output_tokens"] * rates["output"]
    ) / 1_000_000


def _parse_proposals_with_repairs(text: str) -> tuple[Proposals, list[str], bool]:
    """Parse proposals, allowing only audited, equivalent field-name repair."""
    try:
        return Proposals.model_validate_json(text), [], True
    except Exception as original_error:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            raise original_error
        if not isinstance(payload, dict) or not isinstance(payload.get("outfits"), list):
            raise original_error
        actions: list[str] = []
        repaired_payload = dict(payload)
        total_outfits = repaired_payload.get("total_outfits")
        if total_outfits == len(payload["outfits"]):
            repaired_payload.pop("total_outfits")
            actions.append("drop_redundant_total_outfits")
        for extra_field in sorted(set(repaired_payload) - {"outfits"}):
            repaired_payload.pop(extra_field)
            actions.append(f"drop_top_level_field:{extra_field}")
        repaired_outfits = []
        for row in payload["outfits"]:
            if not isinstance(row, dict):
                raise original_error
            repaired = dict(row)
            if "item_ids" not in repaired and isinstance(repaired.get("items"), list):
                item_values = repaired.pop("items")
                if all(isinstance(item, str) for item in item_values):
                    repaired["item_ids"] = item_values
                    actions.append("rename_items_to_item_ids")
                elif all(
                    isinstance(item, dict)
                    and set(item) == {"id"}
                    and isinstance(item["id"], str)
                    for item in item_values
                ):
                    repaired["item_ids"] = [item["id"] for item in item_values]
                    actions.append("extract_item_ids_from_objects")
            if "item_ids" not in repaired:
                slot_fields = (
                    "top", "bottom", "full_body", "outerwear", "shoes", "accessory",
                )
                slot_ids = [
                    repaired.get(field) for field in slot_fields
                    if isinstance(repaired.get(field), str)
                ]
                accessories = repaired.get("accessories")
                if isinstance(accessories, list) and all(
                    isinstance(item, str) for item in accessories
                ):
                    slot_ids.extend(accessories)
                if slot_ids:
                    repaired = {
                        "item_ids": list(dict.fromkeys(slot_ids)),
                        "reason": repaired.get("reason") or "",
                    }
                    actions.append("reshape_slot_fields_to_item_ids")
            repaired_outfits.append(repaired)
        if not actions:
            raise original_error
        return Proposals.model_validate({
            **repaired_payload,
            "outfits": repaired_outfits,
        }), actions, False


def _validate_proposals(
    proposals: Proposals,
    *,
    scenario: dict[str, Any],
    catalog: list[ClothingItemRecord],
    config: Any,
) -> list[dict[str, Any]]:
    allowed = {item.id: item for item in catalog}
    proposal_rows = []
    layered_top_proposals = 0
    for proposal in proposals.outfits:
        codes = []
        if scenario["anchor_item_id"] not in proposal.item_ids:
            codes.append("missing_anchor")
        if len(proposal.item_ids) != len(set(proposal.item_ids)):
            codes.append("duplicate_item")
        if any(item_id not in allowed for item_id in proposal.item_ids):
            codes.append("outside_frozen_catalog")
        members = [allowed[item_id] for item_id in proposal.item_ids if item_id in allowed]
        if len(members) == len(proposal.item_ids):
            codes.extend(structural_rejection_codes(members, require_shoes=False))
            if compatibility_issues(members, config.compatibility_rules):
                codes.append("compatibility_issue")
            layering = assess_outfit_layering(members, config.layering_fit_policy)
            if layering and layering.hard_failure:
                codes.append("physical_layering_failure")
            if not codes and slot(allowed[scenario["anchor_item_id"]]) == "Bottoms":
                top_count = sum(slot(member) == "Tops" for member in members)
                if top_count > 1:
                    layered_top_proposals += 1
                    if layered_top_proposals > 2:
                        codes.append("optional_layer_quota_exceeded")
        proposal_rows.append({
            "item_ids": proposal.item_ids,
            "reason": proposal.reason,
            "valid": not codes,
            "rejection_codes": sorted(set(codes)),
        })
    return proposal_rows


def run_model(
    *, suite_dir: Path, model: str, base_url: str, protocol: str, schema_mode: str,
    api_key_env: str, timeout: float, input_rate: float, cached_rate: float,
    output_rate: float, budget: float, max_scenarios: int = 0,
) -> Path:
    if max_scenarios < 0:
        raise ValueError("max_scenarios must be zero (all) or positive")
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing provider key in {api_key_env}")
    manifest = json.loads((suite_dir / "suite_manifest.json").read_text())
    items_doc = json.loads((suite_dir / "items.json").read_text())
    scenarios = json.loads((suite_dir / "scenarios.json").read_text())
    prompt = (suite_dir / "prompt.txt").read_text()
    schema = json.loads((suite_dir / "output_schema.json").read_text())
    if digest(items_doc) != manifest["items_sha256"] or digest(scenarios) != manifest["scenarios_sha256"]:
        raise RuntimeError("Frozen outfit suite checksum mismatch")
    config = load_config()
    gateway = _gateway(protocol, base_url=base_url, api_key=api_key, schema_mode=schema_mode)
    input_mode = manifest.get("input_mode", "metadata-and-images")
    if input_mode not in INPUT_MODES:
        raise RuntimeError(f"Unsupported frozen input mode: {input_mode}")
    storage = StorageService() if input_mode == "metadata-and-images" else None
    run_dir = suite_dir / "runs" / f"{model.replace('/', '--')}-{uuid4().hex[:8]}"
    (run_dir / "results").mkdir(parents=True)
    rates = {"input": input_rate, "cached_input": cached_rate, "output": output_rate}
    spent = 0.0
    blocked_reason: str | None = None
    for scenario in scenarios[:max_scenarios or None]:
        if spent >= budget:
            break
        catalog = [ClothingItemRecord.model_validate(items_doc[item_id]) for item_id in scenario["catalog_item_ids"]]
        content: list[dict[str, Any]] = [{"type": "input_text", "text": json.dumps(scenario["request"])}]
        signed_urls = []
        for item in catalog:
            content.append({"type": "input_text", "text": json.dumps({
                key: getattr(item, key) for key in (
                    "id", "category", "subtype", "color", "style", "material", "pattern", "fit",
                    "length", "sleeve_length", "layering_role", "wearing_profile", "color_tones",
                    "warmth_level", "formality_score", "occasion", "season",
                )
            }, default=str)})
            if storage is not None:
                url = storage.signed_image_url(item.image_path, expires_in=900)
                if not url or not url.startswith("https://"):
                    raise RuntimeError(f"Image unavailable for frozen item {item.id}")
                signed_urls.append(url)
                content.append({
                    "type": "input_image", "image_url": url, "detail": config.image_detail,
                })
        started = time.perf_counter()
        result_doc: dict[str, Any] = {"scenario_id": scenario["scenario_id"], "status": "failed"}
        try:
            response = gateway.response(
                model=model, timeout=timeout,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": content},
                ],
                schema=schema, schema_name="outfit_proposals",
            )
            usage = _usage(response.payload)
            cost = _estimated_cost(usage, rates)
            spent += cost
            raw_payload: Any = response.payload
            raw_text: Any = response.text
            for url in signed_urls:
                raw_payload = _redact_url(raw_payload, url)
                raw_text = _redact_url(raw_text, url)
            # Persist transport success before schema parsing so malformed
            # model output still has auditable usage, cost and raw text.
            result_doc.update(
                model_call_succeeded=True,
                usage=usage,
                estimated_cost_usd=cost,
                raw_response=raw_payload,
                raw_response_text=raw_text,
            )
            proposals, repair_actions, raw_contract_valid = _parse_proposals_with_repairs(
                response.text,
            )
            result_doc.update(
                raw_contract_valid=raw_contract_valid,
                text_repair_actions=repair_actions,
            )
            proposal_rows = _validate_proposals(
                proposals, scenario=scenario, catalog=catalog, config=config,
            )
            result_doc.update(
                status="succeeded", latency_seconds=round(time.perf_counter() - started, 6),
                proposals=proposal_rows,
            )
        except Exception as error:
            provider_message = getattr(error, "provider_message", None)
            for url in signed_urls:
                provider_message = _redact_url(provider_message, url)
            result_doc.update(
                latency_seconds=round(time.perf_counter() - started, 6),
                error={
                    "type": type(error).__name__,
                    "http_status": getattr(error, "http_status", None),
                    "provider_code": getattr(error, "provider_code", None),
                    "provider_message": provider_message,
                },
            )
            if isinstance(error, OutfitModelError) and (
                error.http_status in {401, 403}
                or error.provider_code in {
                    "credit_balance_exhausted", "insufficient_quota", "invalid_api_key",
                    "billing_hard_limit_reached",
                }
            ):
                blocked_reason = f"provider_{error.http_status}:{error.provider_code}"
        write_json_atomic(run_dir / "results" / f"{scenario['scenario_id']}.json", result_doc)
        if blocked_reason:
            break
    write_json_atomic(run_dir / "run_manifest.json", {
        "schema_version": SCHEMA_VERSION, "suite_id": manifest["suite_id"], "model": model,
        "base_url": base_url, "protocol": protocol, "schema_mode": schema_mode,
        "input_mode": input_mode,
        "pricing_usd_per_million": rates, "budget_usd": budget,
        "production_writes": False, "created_at": utc_now(),
        "state": "blocked" if blocked_reason else "complete", "blocked_reason": blocked_reason,
    })
    summarize(run_dir)
    return run_dir


def reparse_run(run_dir: Path) -> dict[str, Any]:
    """Apply approved deterministic repairs to stored outfit responses."""
    suite_dir = run_dir.parent.parent
    items_doc = json.loads((suite_dir / "items.json").read_text())
    scenarios = {
        row["scenario_id"]: row
        for row in json.loads((suite_dir / "scenarios.json").read_text())
    }
    config = load_config()
    changed = 0
    for result_path in sorted((run_dir / "results").glob("*.json")):
        row = json.loads(result_path.read_text())
        if row.get("status") != "failed" or not row.get("raw_response_text"):
            continue
        try:
            proposals, actions, raw_contract_valid = _parse_proposals_with_repairs(
                row["raw_response_text"],
            )
        except Exception:
            continue
        scenario = scenarios[row["scenario_id"]]
        catalog = [
            ClothingItemRecord.model_validate(items_doc[item_id])
            for item_id in scenario["catalog_item_ids"]
        ]
        proposal_rows = _validate_proposals(
            proposals, scenario=scenario, catalog=catalog, config=config,
        )
        row.update(
            status="succeeded",
            raw_contract_valid=raw_contract_valid,
            text_repair_actions=actions,
            proposals=proposal_rows,
            reparsed_at=utc_now(),
        )
        row.pop("error", None)
        write_json_atomic(result_path, row)
        changed += 1
    result = summarize(run_dir)
    result["offline_reparse"] = {"schema_recovered": changed}
    write_json_atomic(run_dir / "summary.json", result)
    return result


def summarize(run_dir: Path) -> dict[str, Any]:
    results = [json.loads(path.read_text()) for path in sorted((run_dir / "results").glob("*.json"))]
    succeeded = [row for row in results if row.get("status") == "succeeded"]
    called = [
        row for row in results
        if row.get("model_call_succeeded") or row.get("raw_response") is not None
        or row.get("usage") is not None
    ]
    proposals = [proposal for row in succeeded for proposal in row.get("proposals", [])]
    latencies = [float(row["latency_seconds"]) for row in succeeded]
    summary = {
        "schema_version": SCHEMA_VERSION, "generated_at": utc_now(),
        "scenarios_completed": len(results), "scenario_success_rate": len(succeeded) / len(results) if results else None,
        "proposal_count": len(proposals),
        "hard_rule_valid_rate": sum(bool(row["valid"]) for row in proposals) / len(proposals) if proposals else None,
        "mean_valid_proposals_per_scenario": (
            sum(bool(row["valid"]) for row in proposals) / len(succeeded) if succeeded else None
        ),
        "latency_seconds": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "usage": {
            key: sum((row.get("usage") or {}).get(key, 0) for row in called)
            for key in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        "estimated_cost_usd": sum(float(row.get("estimated_cost_usd") or 0) for row in called),
    }
    write_json_atomic(run_dir / "summary.json", summary)
    with (run_dir / "annotation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "scenario_id", "proposal_index", "item_ids", "hard_rule_valid", "rejection_codes",
            "physically_wearable_1_5", "aesthetic_1_5", "would_wear_yes_no", "reviewer_notes",
        ))
        writer.writeheader()
        for row in succeeded:
            for index, proposal in enumerate(row.get("proposals", []), start=1):
                writer.writerow({
                    "scenario_id": row["scenario_id"], "proposal_index": index,
                    "item_ids": " | ".join(proposal["item_ids"]),
                    "hard_rule_valid": proposal["valid"],
                    "rejection_codes": " | ".join(proposal["rejection_codes"]),
                })
    return summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--user-id", required=True)
    prepare.add_argument("--scenarios", type=int, default=10)
    prepare.add_argument("--input-mode", choices=INPUT_MODES, default="metadata-and-images")
    prepare.add_argument(
        "--catalog-limit", type=int, default=0,
        help="Override the production clothing catalog size for a paired capacity test",
    )
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    derive = commands.add_parser("derive-metadata")
    derive.add_argument("--source-suite", type=Path, required=True)
    derive.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    rebalance = commands.add_parser("derive-rebalanced")
    rebalance.add_argument("--source-suite", type=Path, required=True)
    rebalance.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    rebalance.add_argument("--catalog-limit", type=int, default=30)
    rebalance.add_argument("--input-mode", choices=INPUT_MODES, default="metadata-only")
    run = commands.add_parser("run")
    run.add_argument("--suite-dir", type=Path, required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--protocol", choices=("responses", "chat-completions"), required=True)
    run.add_argument(
        "--schema-mode", choices=(STRICT_SCHEMA_MODE,), default=STRICT_SCHEMA_MODE,
        help="Strict JSON Schema is mandatory for comparable shadow evaluations",
    )
    run.add_argument("--api-key-env", required=True)
    run.add_argument("--timeout", type=float, default=180)
    run.add_argument("--input-rate", type=float, required=True)
    run.add_argument("--cached-rate", type=float, required=True)
    run.add_argument("--output-rate", type=float, required=True)
    run.add_argument("--budget", type=float, default=10)
    run.add_argument("--max-scenarios", type=int, default=0, help="0 runs every frozen scenario")
    summary = commands.add_parser("summarize")
    summary.add_argument("--run-dir", type=Path, required=True)
    reparse = commands.add_parser("reparse")
    reparse.add_argument("--run-dir", type=Path, required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        path = prepare_suite(
            user_id=args.user_id, scenarios=args.scenarios,
            output_root=args.output_root, catalog_limit=args.catalog_limit,
            input_mode=args.input_mode,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "derive-metadata":
        path = derive_metadata_only_suite(
            source_suite=args.source_suite.resolve(), output_root=args.output_root,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "derive-rebalanced":
        path = derive_rebalanced_suite(
            source_suite=args.source_suite.resolve(), output_root=args.output_root,
            catalog_limit=args.catalog_limit, input_mode=args.input_mode,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "run":
        path = run_model(
            suite_dir=args.suite_dir.resolve(), model=args.model, base_url=args.base_url,
            protocol=args.protocol, schema_mode=args.schema_mode, api_key_env=args.api_key_env,
            timeout=args.timeout, input_rate=args.input_rate, cached_rate=args.cached_rate,
            output_rate=args.output_rate, budget=args.budget,
            max_scenarios=args.max_scenarios,
        )
        print(json.dumps({"state": "complete", "run_dir": str(path), "summary": summarize(path)}, indent=2))
    elif args.command == "reparse":
        print(json.dumps(reparse_run(args.run_dir.resolve()), indent=2))
    else:
        print(json.dumps(summarize(args.run_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
