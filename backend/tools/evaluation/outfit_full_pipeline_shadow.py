"""Read-only continuation of a frozen clothing run through the production outfit stages.

The clothing proposals come from an existing 30-item quota experiment.  This
runner adds the production semantics that experiment intentionally omitted:
ranked footwear/accessory pools, one joint shoe/accessory choice, one final
whole-outfit review, and the same core/optional projection used by the app.

No production table is read during model execution and no production table is
ever written.  A frozen baseline supplies shoes, bags and accessories.  Every
model request contains at most two composite images.
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
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import ClothingItemRecord
from app.outfits.catalog import rank_score
from app.outfits.compatibility import (
    accessory_role,
    compatibility_issues,
    core_items,
    optional_layer_ids,
    slot,
)
from app.outfits.config import load_config
from app.outfits.diagnostics import OutfitModelError
from app.outfits.footwear import footwear_catalog
from app.outfits.models import CurrentVisualReview
from app.outfits.service import structural_rejection_codes
from app.services.layering_fit import assess_outfit_layering
from app.services.storage_service import StorageService
from tools.evaluation.outfit_model_shadow import (
    STRICT_SCHEMA_MODE,
    _estimated_cost,
    _gateway,
    _usage,
)
from tools.evaluation.outfit_visual_shadow import ITEM_METADATA_FIELDS
from tools.evaluation.recognition_shadow import digest, write_json_atomic


SCHEMA_VERSION = "outfit-full-pipeline-shadow-v1"
IMAGES_PER_CALL = 2
DEFAULT_ROOT = Path("../evaluation/model_migration/outfit_full_pipeline_shadow")
JPEG_QUALITY = 90


class AccessorySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1)
    selected_shoe_id: str | None
    accessory_ids: list[str]
    reason: str = Field(min_length=1)


class AccessorySelectionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: list[AccessorySelection]


class FinalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1)
    review: CurrentVisualReview
    optional_item_reviews: list["OptionalItemDecision"]


class OptionalItemDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1)
    verdict: Literal["clear_improvement", "no_improvement", "uncertain"]
    reason: str = Field(min_length=1)


class FinalReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviews: list[FinalReview]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _chunks(values: list[Any], size: int = IMAGES_PER_CALL) -> list[list[Any]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _normalize_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for field in ("feature_vector", "semantic_vector", "metadata", "recognition_tags"):
        value = normalized.get(field)
        if isinstance(value, str):
            try:
                normalized[field] = json.loads(value)
            except json.JSONDecodeError:
                if field in {"feature_vector", "semantic_vector"}:
                    normalized[field] = None
    return normalized


def _item_document(item: ClothingItemRecord) -> dict[str, Any]:
    return item.model_dump(mode="json")


def _selection_schema(candidate_ids: list[str]) -> dict[str, Any]:
    schema = AccessorySelectionBatch.model_json_schema()
    schema["properties"]["selections"]["minItems"] = len(candidate_ids)
    schema["properties"]["selections"]["maxItems"] = len(candidate_ids)
    schema["$defs"]["AccessorySelection"]["properties"]["candidate_id"] = {
        "type": "string", "enum": candidate_ids,
    }
    return schema


def _review_schema(candidate_ids: list[str], optional_item_ids: list[str] | None = None) -> dict[str, Any]:
    schema = FinalReviewBatch.model_json_schema()
    schema["properties"]["reviews"]["minItems"] = len(candidate_ids)
    schema["properties"]["reviews"]["maxItems"] = len(candidate_ids)
    schema["$defs"]["FinalReview"]["properties"]["candidate_id"] = {
        "type": "string", "enum": candidate_ids,
    }
    if optional_item_ids:
        schema["$defs"]["OptionalItemDecision"]["properties"]["item_id"] = {
            "type": "string", "enum": list(dict.fromkeys(optional_item_ids)),
        }
    return schema


def _validate_order(actual: list[str], expected: list[str], stage: str) -> None:
    if actual != expected:
        raise ValueError(f"{stage} must return every supplied candidate exactly once and in order")


def _metadata(item: ClothingItemRecord) -> dict[str, Any]:
    return {field: getattr(item, field) for field in ITEM_METADATA_FIELDS}


def _selection_context(row: dict[str, Any], items: dict[str, ClothingItemRecord]) -> dict[str, Any]:
    """Mirror production's image-plus-metadata accessory input without extra images."""
    return {
        **row,
        "clothing_items": [_metadata(items[item_id]) for item_id in row["clothing_item_ids"]],
        "shoe_candidates": [_metadata(items[item_id]) for item_id in row["candidate_shoe_ids"]],
        "accessory_candidates": [_metadata(items[item_id]) for item_id in row["candidate_accessory_ids"]],
    }


def _image_bytes(image: Image.Image, max_dimension: int) -> tuple[bytes, dict[str, Any]]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    before = image.size
    if max(image.size) > max_dimension:
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue(), {
        "pre_resize_width": before[0], "pre_resize_height": before[1],
        "output_width": image.width, "output_height": image.height,
        "format": "JPEG", "quality": JPEG_QUALITY,
    }


def _data_url(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _fit_tile(source: Image.Image, size: int) -> Image.Image:
    return ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (size, size), Image.Resampling.LANCZOS)


def _label(item: ClothingItemRecord) -> str:
    return f"{item.subtype or item.category} | {item.color or 'Unknown'} | {item.id[:8]}"


def _compose_sections(
    sections: list[tuple[str, list[tuple[ClothingItemRecord, Image.Image]]]],
    *, max_dimension: int,
) -> tuple[bytes, dict[str, Any]]:
    tile, label_height, heading_height, gap, columns = 250, 42, 42, 12, 4
    populated = [(heading, rows) for heading, rows in sections if rows]
    if not populated:
        raise ValueError("A composite board requires at least one item")
    width = columns * tile + (columns + 1) * gap
    height = gap
    for _, rows in populated:
        height += heading_height + math.ceil(len(rows) / columns) * (tile + label_height + gap)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    y = gap
    audit: list[dict[str, Any]] = []
    for heading, rows in populated:
        draw.rectangle((0, y, width, y + heading_height), fill="#e8eef6")
        draw.text((gap, y + 12), heading, fill="black")
        y += heading_height
        for index, (item, source) in enumerate(rows):
            column, row = index % columns, index // columns
            x = gap + column * (tile + gap)
            item_y = y + row * (tile + label_height + gap)
            canvas.paste(_fit_tile(source, tile), (x, item_y))
            draw.rectangle((x, item_y, x + tile - 1, item_y + tile - 1), outline="#707070", width=2)
            draw.text((x + 5, item_y + tile + 7), _label(item), fill="black")
            audit.append({"section": heading, "item_id": item.id,
                          "source_width": source.width, "source_height": source.height})
        y += math.ceil(len(rows) / columns) * (tile + label_height + gap)
    encoded, size_audit = _image_bytes(canvas, max_dimension)
    return encoded, {"items": audit, "section_count": len(populated), **size_audit}


def _download(
    item: ClothingItemRecord, storage: StorageService, client: httpx.Client,
    cache: dict[str, Image.Image], timeout: float,
) -> Image.Image:
    if item.id in cache:
        return cache[item.id].copy()
    url = storage.signed_image_url(item.image_path, expires_in=900)
    if not url or not url.startswith("https://"):
        path = Path(item.image_path or "")
        if not path.is_file():
            raise RuntimeError(f"Image unavailable for frozen item {item.id}")
        image = Image.open(path)
    else:
        response = client.get(url, timeout=timeout)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
    image.load()
    cache[item.id] = ImageOps.exif_transpose(image).convert("RGB")
    return cache[item.id].copy()


def _accessory_prompt() -> str:
    return (Path(__file__).parents[2] / "app/outfits/prompts/select_accessories.txt").read_text(encoding="utf-8") + """

SHADOW COMPOSITE MODE: Each supplied image is one candidate board with labeled Clothing Base, Shoes, and Optional Accessories sections. Return exactly one selection for each candidate_id in supplied order. Use only IDs listed for that candidate. Bags are optional accessories. The selected shoe is required for admission, but return null rather than force an unsuitable shoe.
Select at most maximum_accessories optional items. A supplied color-responsive candidate is not automatically good, but compare it explicitly with neutral alternatives against the WHOLE outfit palette. Do not default to black merely because it is neutral when a supplied blue, pink, or other outfit color produces a more intentional visible relationship.
"""


def _review_prompt() -> str:
    return (Path(__file__).parents[2] / "app/outfits/prompts/review_visual.txt").read_text(encoding="utf-8") + """

SHADOW COMPOSITE MODE: Each supplied image is one complete Outfit. Review every candidate_id independently and return exactly one result for each supplied candidate_id in order. Do not move garments or conclusions between images.
Return exactly one optional_item_reviews entry for every supplied optional_layer_item_id, in the same order. Judge each optional item independently against the core Outfit. One good bag cannot rescue a weak scarf or hat. Accessories require clear_improvement individually; compatibility, utility, warmth, or being a neutral color is not enough. If no optional items are supplied, return an empty list.
"""


NEUTRAL_COLORS = frozenset({
    "black", "white", "gray", "grey", "beige", "brown", "cream", "silver", "gold",
})


def _color_tokens(item: ClothingItemRecord) -> list[str]:
    return [token.strip().lower() for token in (item.color or "").split(",")
            if token.strip() and token.strip().lower() not in {"unknown", "none"}]


def _shadow_accessories_for(
    clothing: list[ClothingItemRecord], anchor: ClothingItemRecord,
    items: list[ClothingItemRecord], config: Any,
) -> list[ClothingItemRecord]:
    """Color-responsive, role-diverse Top 4 used only by this migration test."""
    clothing_ids = {item.id for item in clothing}
    accessories = [
        item for item in items
        if slot(item) == "Accessories" and item.subtype != "Tights" and item.id not in clothing_ids
    ]
    base_scores = {
        item.id: sum(rank_score(piece, item, config) for piece in clothing)
        for item in accessories
    }
    palette = []
    for piece in clothing:
        for color in _color_tokens(piece):
            if color not in NEUTRAL_COLORS and color not in palette:
                palette.append(color)

    selected: list[ClothingItemRecord] = []
    # Preserve up to two exact color echoes before generic semantic ranking can
    # discard them. Multiple scarf colors may be compared, but structural rules
    # still prevent selecting two scarves in the final Outfit.
    for color in palette[:2]:
        matching = [item for item in accessories if color in _color_tokens(item)]
        if matching:
            # For a cool-weather palette, compare actual same-color scarves
            # before letting a generic multicolor bag or hat consume the color
            # echo slot. The model may still reject both scarves later.
            matching_scarves = [item for item in matching if (item.subtype or "").lower() == "scarf"]
            pool = matching_scarves or matching
            best = max(pool, key=lambda item: (base_scores[item.id], item.id))
            if best not in selected:
                selected.append(best)

    remaining = [item for item in accessories if item not in selected]
    groups: dict[str, list[ClothingItemRecord]] = defaultdict(list)
    for item in sorted(remaining, key=lambda value: (-base_scores[value.id], value.id)):
        groups[accessory_role(item)].append(item)
    while len(selected) < config.vision_accessory_limit and any(groups.values()):
        for role in sorted(groups):
            if groups[role] and len(selected) < config.vision_accessory_limit:
                selected.append(groups[role].pop(0))
    if slot(anchor) == "Accessories" and anchor.subtype != "Tights" and anchor.id not in {i.id for i in selected}:
        selected = selected[:max(0, config.vision_accessory_limit - 1)] + [anchor]
    return selected[:config.vision_accessory_limit]


def _shadow_clothing_codes(items: list[ClothingItemRecord]) -> list[str]:
    """Experimental thermal coverage rule absent from the current production policy."""
    ski_pants = [item for item in items if item.subtype == "Ski Pants"]
    if not ski_pants:
        return []
    upper = [item for item in items if slot(item) in {"Tops", "Outerwear"}]
    sufficiently_warm = any((item.warmth_level or 0) >= 3 for item in upper)
    if not sufficiently_warm:
        return ["ski_pants_without_warm_upper_coverage"]
    return []


def prepare_suite(
    *, generation_suite: Path, source_run: Path, baseline_items: Path,
    output_root: Path, max_proposals_per_scenario: int = 8,
    selection_max_dimension: int = 1536, final_max_dimension: int = 1024,
) -> Path:
    if max_proposals_per_scenario < 1:
        raise ValueError("max_proposals_per_scenario must be positive")
    generation_manifest = _read(generation_suite / "suite_manifest.json")
    run_manifest = _read(source_run / "run_manifest.json")
    frozen_clothing = _read(generation_suite / "items.json")
    scenarios = {row["scenario_id"]: row for row in _read(generation_suite / "scenarios.json")}
    if run_manifest.get("suite_id") != generation_manifest.get("suite_id"):
        raise RuntimeError("Source run does not belong to the supplied generation suite")

    baseline_rows = [_normalize_snapshot_row(row) for row in _read(baseline_items)]
    all_items: dict[str, ClothingItemRecord] = {}
    for row in baseline_rows:
        item = ClothingItemRecord.model_validate(row)
        if item.user_id == generation_manifest["user_id"] and item.recognition_status in {"complete", "manual"}:
            all_items[item.id] = item
    for item_id, row in frozen_clothing.items():
        all_items[item_id] = ClothingItemRecord.model_validate(row)

    config = load_config()
    candidates: list[dict[str, Any]] = []
    pre_accessory_rejections: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for result_path in sorted((source_run / "results").glob("*.json")):
        result = _read(result_path)
        scenario_id = result["scenario_id"]
        if result.get("status") != "succeeded" or scenario_id not in scenarios:
            continue
        scenario = scenarios[scenario_id]
        anchor = all_items[scenario["anchor_item_id"]]
        valid = [row for row in result.get("proposals", []) if row.get("valid")]
        for index, proposal in enumerate(valid[:max_proposals_per_scenario], start=1):
            clothing = [all_items[item_id] for item_id in proposal["item_ids"]]
            experimental_codes = _shadow_clothing_codes(clothing)
            if experimental_codes:
                pre_accessory_rejections.append({
                    "scenario_id": scenario_id,
                    "source_candidate_index": index,
                    "item_ids": proposal["item_ids"],
                    "rejection_codes": experimental_codes,
                })
                continue
            shoes = footwear_catalog(clothing, list(all_items.values()), config, anchor)[:config.vision_footwear_limit]
            accessories = _shadow_accessories_for(clothing, anchor, list(all_items.values()), config)
            candidate_id = f"{scenario_id}-C{index:02d}"
            row = {
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
                "anchor_item_id": anchor.id,
                "clothing_item_ids": [item.id for item in clothing],
                "candidate_shoe_ids": [item.id for item in shoes],
                "candidate_accessory_ids": [item.id for item in accessories],
                "maximum_accessories": min(2, max(0, config.max_items_per_outfit - len(clothing) - 1)),
                "generation_reason": proposal.get("reason") or "",
            }
            candidates.append(row)
            used_ids.update(row["clothing_item_ids"] + row["candidate_shoe_ids"] + row["candidate_accessory_ids"])
    if not candidates:
        raise RuntimeError("No hard-rule-valid clothing proposals were available")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"full-suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    items_doc = {item_id: _item_document(all_items[item_id]) for item_id in sorted(used_ids)}
    selection_prompt, review_prompt = _accessory_prompt(), _review_prompt()
    write_json_atomic(suite_dir / "items.json", items_doc)
    write_json_atomic(suite_dir / "candidates.json", candidates)
    write_json_atomic(suite_dir / "pre_accessory_rejections.json", pre_accessory_rejections)
    (suite_dir / "accessory_prompt.txt").write_text(selection_prompt, encoding="utf-8")
    (suite_dir / "review_prompt.txt").write_text(review_prompt, encoding="utf-8")
    write_json_atomic(suite_dir / "suite_manifest.json", {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "user_id": generation_manifest["user_id"],
        "generation_suite": generation_manifest["suite_id"],
        "source_run": str(source_run.resolve()),
        "source_generation_model": run_manifest["model"],
        "baseline_items": str(baseline_items.resolve()),
        "candidate_count": len(candidates),
        "pre_accessory_rejection_count": len(pre_accessory_rejections),
        "scenario_count": len({row["scenario_id"] for row in candidates}),
        "images_per_call": IMAGES_PER_CALL,
        "selection_max_dimension": selection_max_dimension,
        "final_max_dimension": final_max_dimension,
        "items_sha256": digest(items_doc),
        "candidates_sha256": digest(candidates),
        "accessory_prompt_sha256": hashlib.sha256(selection_prompt.encode()).hexdigest(),
        "review_prompt_sha256": hashlib.sha256(review_prompt.encode()).hexdigest(),
        "policy": {
            "require_shoes": True,
            "footwear_candidates": config.vision_footwear_limit,
            "accessory_candidates": config.vision_accessory_limit,
            "max_items_per_outfit": config.max_items_per_outfit,
            "maximum_optional_accessories": 2,
            "accessory_recall": "whole-outfit-color-responsive-role-diverse-v1",
            "ski_thermal_coverage_rule": "ski-pants-require-upper-warmth-at-least-3",
            "per_optional_item_review": True,
            "early_stop_after_first_admitted_per_scenario": True,
            "production_core_optional_projection": True,
        },
        "safety": {"production_writes": False, "signed_urls_persisted": False},
    })
    return suite_dir


def _call_with_retry(
    *, gateway: Any, model: str, timeout: float, prompt: str,
    content: list[dict[str, Any]], schema: dict[str, Any], schema_name: str,
    max_attempts: int,
) -> tuple[Any, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = gateway.response(
                model=model, timeout=timeout,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": content},
                ],
                schema=schema, schema_name=schema_name,
            )
            attempts.append({"attempt": attempt, "status": "succeeded",
                             "latency_seconds": round(time.perf_counter() - started, 6)})
            return response, attempts
        except Exception as error:
            status = getattr(error, "http_status", None)
            retriable = isinstance(error, (httpx.TimeoutException, TimeoutError)) or status == 429 or (
                isinstance(status, int) and status >= 500
            )
            attempts.append({
                "attempt": attempt, "status": "failed",
                "latency_seconds": round(time.perf_counter() - started, 6),
                "error": {"type": type(error).__name__, "http_status": status,
                          "provider_code": getattr(error, "provider_code", None),
                          "message": str(error)[:1000]},
                "retriable": retriable,
            })
            if not retriable or attempt >= max_attempts:
                raise
    raise RuntimeError("Unreachable retry state")


def _hard_rule_codes(items: list[ClothingItemRecord], config: Any) -> list[str]:
    codes = structural_rejection_codes(items, require_shoes=True)
    codes.extend(_shadow_clothing_codes(items))
    if compatibility_issues(items, config.compatibility_rules):
        codes.append("compatibility_issue")
    layering = assess_outfit_layering(items, config.layering_fit_policy)
    if layering and layering.hard_failure:
        codes.append("physical_layering_failure")
    return sorted(set(codes))


def _project(
    members: list[ClothingItemRecord], review: CurrentVisualReview, config: Any,
    optional_item_reviews: list[OptionalItemDecision] | None = None,
) -> dict[str, Any]:
    core = core_items(members, require_shoes=True)
    extras = [item for item in members if item.id not in {value.id for value in core}]
    admitted = review.core.passes() and not _hard_rule_codes(core, config)
    approved_extras: list[ClothingItemRecord] = []
    optional_reason = "core_failed"
    if admitted and extras:
        decisions = {decision.item_id: decision for decision in optional_item_reviews or []}
        if decisions:
            for item in extras:
                decision = decisions.get(item.id)
                if decision and (decision.verdict == "clear_improvement" or (
                    slot(item) == "Outerwear" and decision.verdict == "no_improvement"
                )):
                    approved_extras.append(item)
            optional_reason = "per_item_review"
        elif review.optional_layering.verdict == "clear_improvement":
            # Backward-compatible path for historical stored test responses.
            approved_extras = extras
            optional_reason = "legacy_group_clear_improvement"
        elif review.optional_layering.verdict == "no_improvement":
            approved_extras = [item for item in extras if slot(item) == "Outerwear"]
            optional_reason = "outerwear_temperature_variant" if approved_extras else "removed_no_improvement"
        else:
            optional_reason = f"removed_{review.optional_layering.verdict}"
        if approved_extras:
            full_members = core + approved_extras
            if not review.full.passes() or _hard_rule_codes(full_members, config):
                approved_extras = []
                optional_reason = "removed_failed_full_review"
    return {
        "admitted": admitted,
        "core_item_ids": [item.id for item in core],
        "optional_item_ids": [item.id for item in approved_extras],
        "removed_optional_item_ids": [item.id for item in extras if item not in approved_extras],
        "optional_projection_reason": optional_reason,
    }


def _save_board(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _export_contact_sheets(run_dir: Path, selected: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []
    for page_index, page in enumerate(_chunks(selected, 5), start=1):
        images = [
            Image.open(run_dir / (row.get("projection_preview_path") or row["preview_path"])).convert("RGB")
            for row in page
        ]
        width = max(image.width for image in images)
        labeled = []
        for row, image in zip(page, images):
            if image.width != width:
                image = ImageOps.contain(image, (width, image.height * width // image.width))
            panel = Image.new("RGB", (width, image.height + 52), "white")
            ImageDraw.Draw(panel).text(
                (14, 16), f"{row['scenario_id']} | {row['candidate_id']}", fill="black",
            )
            panel.paste(image, (0, 52))
            labeled.append(panel)
        canvas = Image.new("RGB", (width, sum(image.height for image in labeled) + 16 * (len(labeled) - 1)), "white")
        y = 0
        for image in labeled:
            canvas.paste(image, (0, y)); y += image.height + 16
        path = run_dir / "final_previews" / f"final-outfits-{page_index}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(path, format="JPEG", quality=90)
        output.append(str(path.relative_to(run_dir)))
    return output


def run_model(
    *, suite_dir: Path, model: str, base_url: str, protocol: str,
    schema_mode: str, api_key_env: str, timeout: float, input_rate: float,
    cached_rate: float, output_rate: float, budget: float,
    max_attempts: int = 2, max_scenarios: int = 0,
) -> Path:
    if schema_mode != STRICT_SCHEMA_MODE:
        raise ValueError("The full shadow pipeline requires strict JSON Schema")
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing provider key in {api_key_env}")
    manifest = _read(suite_dir / "suite_manifest.json")
    items_doc = _read(suite_dir / "items.json")
    candidates = _read(suite_dir / "candidates.json")
    accessory_prompt = (suite_dir / "accessory_prompt.txt").read_text(encoding="utf-8")
    review_prompt = (suite_dir / "review_prompt.txt").read_text(encoding="utf-8")
    if digest(items_doc) != manifest["items_sha256"] or digest(candidates) != manifest["candidates_sha256"]:
        raise RuntimeError("Frozen full-pipeline suite checksum mismatch")
    if hashlib.sha256(accessory_prompt.encode()).hexdigest() != manifest["accessory_prompt_sha256"]:
        raise RuntimeError("Frozen accessory prompt checksum mismatch")
    if hashlib.sha256(review_prompt.encode()).hexdigest() != manifest["review_prompt_sha256"]:
        raise RuntimeError("Frozen review prompt checksum mismatch")

    items = {item_id: ClothingItemRecord.model_validate(row) for item_id, row in items_doc.items()}
    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_scenario[candidate["scenario_id"]].append(candidate)
    gateway = _gateway(protocol, base_url=base_url, api_key=api_key, schema_mode=schema_mode)
    storage, client, image_cache = StorageService(), httpx.Client(http2=False), {}
    config = load_config()
    rates = {"input": input_rate, "cached_input": cached_rate, "output": output_rate}
    run_dir = suite_dir / "runs" / f"{model.replace('/', '--')}-{uuid4().hex[:8]}"
    (run_dir / "results").mkdir(parents=True)
    spent, calls = 0.0, 0
    scenario_ids = sorted(by_scenario)[:max_scenarios or None]

    try:
        for scenario_id in scenario_ids:
            scenario_result: dict[str, Any] = {
                "scenario_id": scenario_id, "status": "exhausted", "waves": [], "selected": None,
            }
            for wave_index, batch in enumerate(_chunks(by_scenario[scenario_id]), start=1):
                if spent >= budget:
                    scenario_result["status"] = "budget_exhausted"
                    break
                candidate_ids = [row["candidate_id"] for row in batch]
                selection_content: list[dict[str, Any]] = [{
                    "type": "input_text", "text": json.dumps({
                        "candidates": [_selection_context(row, items) for row in batch],
                    }, default=str),
                }]
                selection_audits = []
                for row in batch:
                    sections = []
                    for heading, key in (("CLOTHING BASE", "clothing_item_ids"),
                                         ("SHOE CANDIDATES", "candidate_shoe_ids"),
                                         ("OPTIONAL BAGS / ACCESSORIES", "candidate_accessory_ids")):
                        section = [(items[item_id], _download(items[item_id], storage, client, image_cache, timeout))
                                   for item_id in row[key]]
                        sections.append((heading, section))
                    board, audit = _compose_sections(
                        sections, max_dimension=int(manifest["selection_max_dimension"]),
                    )
                    relative = Path("artifacts/selection_boards") / f"{row['candidate_id']}.jpg"
                    _save_board(run_dir / relative, board)
                    selection_audits.append({"candidate_id": row["candidate_id"],
                                             "path": str(relative), **audit})
                    selection_content.append({"type": "input_image", "image_url": _data_url(board), "detail": "high"})
                wave: dict[str, Any] = {"wave": wave_index, "candidate_ids": candidate_ids,
                                       "selection_boards": selection_audits}
                try:
                    response, attempts = _call_with_retry(
                        gateway=gateway, model=model, timeout=timeout, prompt=accessory_prompt,
                        content=selection_content, schema=_selection_schema(candidate_ids),
                        schema_name="outfit_accessory_selection", max_attempts=max_attempts,
                    )
                    calls += len(attempts)
                    usage = _usage(response.payload); cost = _estimated_cost(usage, rates); spent += cost
                    parsed = AccessorySelectionBatch.model_validate_json(response.text)
                    _validate_order([row.candidate_id for row in parsed.selections], candidate_ids, "Accessory selection")
                    wave["selection_call"] = {
                        "status": "succeeded", "attempts": attempts, "usage": usage,
                        "estimated_cost_usd": cost, "raw_response": response.payload,
                        "raw_response_text": response.text,
                    }
                except Exception as error:
                    wave["selection_call"] = {"status": "failed", "error": {
                        "type": type(error).__name__, "http_status": getattr(error, "http_status", None),
                        "provider_code": getattr(error, "provider_code", None), "message": str(error)[:1000],
                    }}
                    scenario_result["waves"].append(wave)
                    continue

                complete = []
                batch_by_id = {row["candidate_id"]: row for row in batch}
                for selection in parsed.selections:
                    source = batch_by_id[selection.candidate_id]
                    rejection_codes = []
                    if selection.selected_shoe_id not in source["candidate_shoe_ids"]:
                        rejection_codes.append("no_or_invalid_selected_shoe")
                    if len(selection.accessory_ids) != len(set(selection.accessory_ids)):
                        rejection_codes.append("duplicate_accessory")
                    if not set(selection.accessory_ids) <= set(source["candidate_accessory_ids"]):
                        rejection_codes.append("accessory_outside_candidate_pool")
                    if len(selection.accessory_ids) > source["maximum_accessories"]:
                        rejection_codes.append("too_many_accessories")
                    if rejection_codes:
                        complete.append({"candidate_id": selection.candidate_id,
                                         "selection": selection.model_dump(mode="json"),
                                         "rejection_codes": rejection_codes})
                        continue
                    ids = source["clothing_item_ids"] + [selection.selected_shoe_id] + selection.accessory_ids
                    members = [items[item_id] for item_id in ids]
                    rejection_codes = _hard_rule_codes(members, config)
                    complete.append({"candidate_id": selection.candidate_id,
                                     "selection": selection.model_dump(mode="json"),
                                     "item_ids": ids, "rejection_codes": rejection_codes})
                wave["complete_candidates"] = complete
                reviewable = [row for row in complete if not row["rejection_codes"]]
                if not reviewable:
                    scenario_result["waves"].append(wave)
                    continue

                review_content: list[dict[str, Any]] = [{
                    "type": "input_text", "text": json.dumps({"candidates": [
                        {"candidate_id": row["candidate_id"],
                         "core_item_ids": [i.id for i in core_items([items[x] for x in row["item_ids"]], require_shoes=True)],
                         "full_item_ids": row["item_ids"],
                         "optional_layer_item_ids": optional_layer_ids([items[x] for x in row["item_ids"]], require_shoes=True)}
                        for row in reviewable
                    ]}),
                }]
                final_audits = []
                for row in reviewable:
                    members = [items[item_id] for item_id in row["item_ids"]]
                    sections = [("COMPLETE OUTFIT", [
                        (item, _download(item, storage, client, image_cache, timeout)) for item in members
                    ])]
                    board, audit = _compose_sections(
                        sections, max_dimension=int(manifest["final_max_dimension"]),
                    )
                    relative = Path("artifacts/final_outfits") / f"{row['candidate_id']}.jpg"
                    _save_board(run_dir / relative, board)
                    row["preview_path"] = str(relative)
                    final_audits.append({"candidate_id": row["candidate_id"], "path": str(relative), **audit})
                    review_content.append({"type": "input_text", "text": json.dumps({
                        "candidate_id": row["candidate_id"], "items": [_metadata(item) for item in members],
                    }, default=str)})
                    review_content.append({"type": "input_image", "image_url": _data_url(board), "detail": "high"})
                review_ids = [row["candidate_id"] for row in reviewable]
                expected_optional_ids = {
                    row["candidate_id"]: optional_layer_ids(
                        [items[item_id] for item_id in row["item_ids"]], require_shoes=True,
                    )
                    for row in reviewable
                }
                try:
                    response, attempts = _call_with_retry(
                        gateway=gateway, model=model, timeout=timeout, prompt=review_prompt,
                        content=review_content, schema=_review_schema(
                            review_ids,
                            [item_id for candidate_id in review_ids
                             for item_id in expected_optional_ids[candidate_id]],
                        ),
                        schema_name="outfit_full_visual_review", max_attempts=max_attempts,
                    )
                    calls += len(attempts)
                    usage = _usage(response.payload); cost = _estimated_cost(usage, rates); spent += cost
                    parsed_reviews = FinalReviewBatch.model_validate_json(response.text)
                    _validate_order([row.candidate_id for row in parsed_reviews.reviews], review_ids, "Final review")
                    for result in parsed_reviews.reviews:
                        _validate_order(
                            [decision.item_id for decision in result.optional_item_reviews],
                            expected_optional_ids[result.candidate_id],
                            f"Optional item review for {result.candidate_id}",
                        )
                    wave["review_call"] = {
                        "status": "succeeded", "attempts": attempts, "usage": usage,
                        "estimated_cost_usd": cost, "raw_response": response.payload,
                        "raw_response_text": response.text, "outfit_images": final_audits,
                    }
                except Exception as error:
                    wave["review_call"] = {"status": "failed", "error": {
                        "type": type(error).__name__, "http_status": getattr(error, "http_status", None),
                        "provider_code": getattr(error, "provider_code", None), "message": str(error)[:1000],
                    }}
                    scenario_result["waves"].append(wave)
                    continue

                review_by_id = {row.candidate_id: row for row in parsed_reviews.reviews}
                projections = []
                for row in reviewable:
                    result = review_by_id[row["candidate_id"]]
                    projection = _project(
                        [items[item_id] for item_id in row["item_ids"]], result.review, config,
                        result.optional_item_reviews,
                    )
                    projections.append({
                        **row,
                        "review": result.review.model_dump(mode="json"),
                        "optional_item_reviews": [
                            decision.model_dump(mode="json") for decision in result.optional_item_reviews
                        ],
                        **projection,
                    })
                wave["projections"] = projections
                scenario_result["waves"].append(wave)
                admitted = [row for row in projections if row["admitted"]]
                if admitted:
                    scenario_result["status"] = "selected"
                    scenario_result["selected"] = admitted[0]
                    break
            write_json_atomic(run_dir / "results" / f"{scenario_id}.json", scenario_result)
    finally:
        client.close()

    write_json_atomic(run_dir / "run_manifest.json", {
        "schema_version": SCHEMA_VERSION, "suite_id": manifest["suite_id"],
        "model": model, "base_url": base_url, "protocol": protocol,
        "schema_mode": schema_mode, "images_per_call": IMAGES_PER_CALL,
        "max_attempts": max_attempts, "pricing_usd_per_million": rates,
        "budget_usd": budget, "production_writes": False, "created_at": utc_now(),
        "calls_attempted": calls, "estimated_cost_usd": spent,
    })
    summarize(run_dir)
    return run_dir


def summarize(run_dir: Path) -> dict[str, Any]:
    results = [_read(path) for path in sorted((run_dir / "results").glob("*.json"))]
    selected = [{"scenario_id": row["scenario_id"], **row["selected"]}
                for row in results if row.get("selected")]
    selection_calls = [wave.get("selection_call") for row in results for wave in row.get("waves", [])
                       if wave.get("selection_call")]
    review_calls = [wave.get("review_call") for row in results for wave in row.get("waves", [])
                    if wave.get("review_call")]
    completed_calls = [row for row in selection_calls + review_calls if row.get("status") == "succeeded"]
    selections = [entry for row in results for wave in row.get("waves", [])
                  for entry in wave.get("complete_candidates", [])]
    valid_selections = [row for row in selections if not row.get("rejection_codes")]
    optional_selected = [row for row in valid_selections if row["selection"].get("accessory_ids")]
    latencies = [attempt["latency_seconds"] for call in completed_calls
                 for attempt in call.get("attempts", []) if attempt.get("status") == "succeeded"]
    contact_sheets = _export_contact_sheets(run_dir, selected) if selected else []
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "scenarios_completed": len(results),
        "final_outfit_count": len(selected),
        "anchor_coverage": len(selected) / len(results) if results else None,
        "selection_calls": len(selection_calls),
        "final_review_calls": len(review_calls),
        "model_call_success_rate": len(completed_calls) / len(selection_calls + review_calls)
        if selection_calls or review_calls else None,
        "shoe_selection_valid_rate": len(valid_selections) / len(selections) if selections else None,
        "optional_accessory_selection_rate": len(optional_selected) / len(valid_selections) if valid_selections else None,
        "final_optional_retention_rate": sum(bool(row["optional_item_ids"]) for row in selected) / len(selected)
        if selected else None,
        "latency_seconds": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "usage": {key: sum((call.get("usage") or {}).get(key, 0) for call in completed_calls)
                  for key in ("input_tokens", "cached_input_tokens", "output_tokens")},
        "estimated_cost_usd": sum(float(call.get("estimated_cost_usd") or 0) for call in completed_calls),
        "contact_sheets": contact_sheets,
    }
    write_json_atomic(run_dir / "summary.json", summary)
    write_json_atomic(run_dir / "final_outfits.json", selected)
    suite_items = {
        item_id: ClothingItemRecord.model_validate(row)
        for item_id, row in _read(run_dir.parent.parent / "items.json").items()
    }
    with (run_dir / "final_outfits.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "scenario_id", "candidate_id", "core_items", "shoe", "optional_items",
            "optional_projection_reason", "preview_path",
        ))
        writer.writeheader()
        for row in selected:
            describe = lambda item_id: (
                f"{suite_items[item_id].subtype or suite_items[item_id].category}"
                f" ({suite_items[item_id].color}; {item_id[:8]})"
            )
            shoe_ids = [item_id for item_id in row["core_item_ids"] if slot(suite_items[item_id]) == "Shoes"]
            writer.writerow({
                "scenario_id": row["scenario_id"], "candidate_id": row["candidate_id"],
                "core_items": " | ".join(describe(item_id) for item_id in row["core_item_ids"]),
                "shoe": " | ".join(describe(item_id) for item_id in shoe_ids),
                "optional_items": " | ".join(describe(item_id) for item_id in row["optional_item_ids"]),
                "optional_projection_reason": row["optional_projection_reason"],
                "preview_path": row["preview_path"],
            })
    with (run_dir / "annotation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "scenario_id", "candidate_id", "core_item_ids", "optional_item_ids",
            "physically_wearable_yes_no", "shoe_appropriate_yes_no",
            "aesthetic_1_5", "would_wear_yes_no", "notes",
        ))
        writer.writeheader()
        for row in selected:
            writer.writerow({
                "scenario_id": row["scenario_id"], "candidate_id": row["candidate_id"],
                "core_item_ids": ",".join(row["core_item_ids"]),
                "optional_item_ids": ",".join(row["optional_item_ids"]),
            })
    return summary


def export_projected_previews(run_dir: Path, timeout: float = 120) -> dict[str, Any]:
    """Render only the retained core and optional projection; never call a model."""
    suite_dir = run_dir.parent.parent
    items = {
        item_id: ClothingItemRecord.model_validate(row)
        for item_id, row in _read(suite_dir / "items.json").items()
    }
    selected = _read(run_dir / "final_outfits.json")
    storage, client, cache = StorageService(), httpx.Client(http2=False), {}
    try:
        for row in selected:
            retained_ids = row["core_item_ids"] + row["optional_item_ids"]
            members = [items[item_id] for item_id in retained_ids]
            board, _ = _compose_sections([(
                "FINAL RETAINED OUTFIT",
                [(item, _download(item, storage, client, cache, timeout)) for item in members],
            )], max_dimension=1024)
            relative = Path("artifacts/projected_outfits") / f"{row['candidate_id']}.jpg"
            _save_board(run_dir / relative, board)
            row["projection_preview_path"] = str(relative)
    finally:
        client.close()
    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "model_calls": 0,
        "outfits": [{
            "scenario_id": row["scenario_id"], "candidate_id": row["candidate_id"],
            "core_item_ids": row["core_item_ids"], "optional_item_ids": row["optional_item_ids"],
            "preview_path": row["projection_preview_path"],
        } for row in selected],
    }
    write_json_atomic(run_dir / "projected_preview_index.json", index)
    index["contact_sheets"] = _export_contact_sheets(run_dir, selected)
    write_json_atomic(run_dir / "projected_preview_index.json", index)
    return index


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--generation-suite", type=Path, required=True)
    prepare.add_argument("--source-run", type=Path, required=True)
    prepare.add_argument("--baseline-items", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    prepare.add_argument("--max-proposals-per-scenario", type=int, default=8)
    prepare.add_argument("--selection-max-dimension", type=int, default=1536)
    prepare.add_argument("--final-max-dimension", type=int, default=1024)
    run = commands.add_parser("run")
    run.add_argument("--suite-dir", type=Path, required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--protocol", choices=("responses", "chat-completions"), required=True)
    run.add_argument("--schema-mode", choices=(STRICT_SCHEMA_MODE,), default=STRICT_SCHEMA_MODE)
    run.add_argument("--api-key-env", required=True)
    run.add_argument("--timeout", type=float, default=240)
    run.add_argument("--input-rate", type=float, required=True)
    run.add_argument("--cached-rate", type=float, required=True)
    run.add_argument("--output-rate", type=float, required=True)
    run.add_argument("--budget", type=float, default=1)
    run.add_argument("--max-attempts", type=int, choices=(1, 2), default=2)
    run.add_argument("--max-scenarios", type=int, default=0)
    summary = commands.add_parser("summarize")
    summary.add_argument("--run-dir", type=Path, required=True)
    export = commands.add_parser("export-projected")
    export.add_argument("--run-dir", type=Path, required=True)
    export.add_argument("--timeout", type=float, default=120)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        path = prepare_suite(
            generation_suite=args.generation_suite.resolve(), source_run=args.source_run.resolve(),
            baseline_items=args.baseline_items.resolve(), output_root=args.output_root,
            max_proposals_per_scenario=args.max_proposals_per_scenario,
            selection_max_dimension=args.selection_max_dimension,
            final_max_dimension=args.final_max_dimension,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "run":
        path = run_model(
            suite_dir=args.suite_dir.resolve(), model=args.model, base_url=args.base_url,
            protocol=args.protocol, schema_mode=args.schema_mode, api_key_env=args.api_key_env,
            timeout=args.timeout, input_rate=args.input_rate, cached_rate=args.cached_rate,
            output_rate=args.output_rate, budget=args.budget, max_attempts=args.max_attempts,
            max_scenarios=args.max_scenarios,
        )
        print(json.dumps({"state": "complete", "run_dir": str(path), "summary": summarize(path)}, indent=2))
    elif args.command == "summarize":
        print(json.dumps(summarize(args.run_dir.resolve()), indent=2))
    else:
        print(json.dumps(export_projected_previews(
            args.run_dir.resolve(), timeout=args.timeout,
        ), indent=2))


if __name__ == "__main__":
    main()
