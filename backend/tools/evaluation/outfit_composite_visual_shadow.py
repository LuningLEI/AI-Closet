"""Read-only batched visual review using one composite image per Outfit.

Every Outfit is rendered as one labeled contact sheet containing all of its
garments.  Two Outfit sheets are reviewed per provider request, so eight
proposals for one anchor require four visual calls.  Production tables are
never written and signed image URLs are never persisted.
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
from app.services.storage_service import StorageService
from tools.evaluation.outfit_model_shadow import (
    STRICT_SCHEMA_MODE,
    _estimated_cost,
    _gateway,
    _usage,
)
from tools.evaluation.outfit_visual_shadow import ITEM_METADATA_FIELDS
from tools.evaluation.recognition_shadow import digest, write_json_atomic


SCHEMA_VERSION = "outfit-composite-visual-shadow-v1"
DEFAULT_OUTFITS_PER_ANCHOR = 8
OUTFITS_PER_CALL = 2
JPEG_QUALITY = 90


class CompositeCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["pass", "fail", "uncertain"]
    reason: str = Field(min_length=1)


class CompositeOutfitReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outfit_id: str = Field(min_length=1)
    physical_fit: CompositeCriterion
    style_silhouette: CompositeCriterion
    color_pattern: CompositeCriterion
    thermal_occasion: CompositeCriterion


class CompositeReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviews: list[CompositeOutfitReview]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prompt() -> str:
    return """You are the final visual compatibility gate for complete outfits.
Each supplied image is one Outfit contact sheet. Every tile inside that image is a separate real garment in that Outfit; labels identify the corresponding item. Review each Outfit independently and never transfer garments, evidence or conclusions between the two images.

physical_fit: Can every garment be worn together, including upper/lower layering capacity, coverage, bulk and competing volume?
style_silhouette: Do sportiness, formality, cuts, drape, proportions and visual weight form an intentional complete outfit?
color_pattern: Are the visible colors and patterns coherent rather than merely sharing a metadata label?
thermal_occasion: Do warmth, exposure, purpose and occasion make sense across the complete outfit?

Flat-lay photos cannot prove every body-specific fit detail. Use uncertain when evidence is genuinely insufficient. Fail concrete visible incompatibilities, including a restrictive outer layer over a bulky top or an athletic performance top combined with an elegant formal bottom. Do not invent garments, styling changes or an occasion to rescue a failed Outfit.

Return exactly one review for every supplied outfit_id, in supplied order, and no additional reviews."""


def _chunks(values: list[Any], size: int = OUTFITS_PER_CALL) -> list[list[Any]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _batch_schema(outfit_ids: list[str]) -> dict[str, Any]:
    schema = CompositeReviewBatch.model_json_schema()
    review_array = schema["properties"]["reviews"]
    review_array["minItems"] = len(outfit_ids)
    review_array["maxItems"] = len(outfit_ids)
    schema["$defs"]["CompositeOutfitReview"]["properties"]["outfit_id"] = {
        "type": "string", "enum": outfit_ids,
    }
    return schema


def _tile_label(item: ClothingItemRecord) -> str:
    name = item.subtype or item.category
    colors = item.color or "Unknown"
    return f"{name} | {colors} | {item.id[:8]}"


def _compose_outfit_image(
    sources: list[tuple[ClothingItemRecord, Image.Image]], *, max_dimension: int,
) -> tuple[str, dict[str, Any]]:
    if not sources:
        raise ValueError("An Outfit composite requires at least one garment image")
    columns = min(3, len(sources))
    rows = math.ceil(len(sources) / columns)
    tile = 320
    label_height = 48
    gap = 12
    width = columns * tile + (columns + 1) * gap
    height = rows * (tile + label_height) + (rows + 1) * gap
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    source_audits = []
    for index, (item, source) in enumerate(sources):
        image = ImageOps.exif_transpose(source).convert("RGB")
        source_audits.append({
            "item_id": item.id,
            "source_width": image.width,
            "source_height": image.height,
        })
        fitted = ImageOps.fit(image, (tile, tile), method=Image.Resampling.LANCZOS)
        column = index % columns
        row = index // columns
        x = gap + column * (tile + gap)
        y = gap + row * (tile + label_height + gap)
        canvas.paste(fitted, (x, y))
        draw.rectangle((x, y, x + tile - 1, y + tile - 1), outline="#707070", width=2)
        draw.text((x + 6, y + tile + 8), _tile_label(item), fill="black")
    original_size = canvas.size
    if max(canvas.size) > max_dimension:
        canvas.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}", {
        "source_items": source_audits,
        "tile_count": len(sources),
        "layout": {"columns": columns, "rows": rows},
        "pre_resize_width": original_size[0],
        "pre_resize_height": original_size[1],
        "output_width": canvas.width,
        "output_height": canvas.height,
        "format": "JPEG",
        "quality": JPEG_QUALITY,
    }


def prepare_composite_suite(
    *, generation_suite: Path, source_run: Path, output_root: Path,
    max_outfits_per_scenario: int = DEFAULT_OUTFITS_PER_ANCHOR,
    composite_max_dimension: int = 1024,
) -> Path:
    if max_outfits_per_scenario < 1 or composite_max_dimension < 1:
        raise ValueError("Outfit count and composite dimension must be positive")
    generation_manifest = _read(generation_suite / "suite_manifest.json")
    source_manifest = _read(source_run / "run_manifest.json")
    items = _read(generation_suite / "items.json")
    scenarios = {row["scenario_id"]: row for row in _read(generation_suite / "scenarios.json")}
    outfits = []
    for result_path in sorted((source_run / "results").glob("*.json")):
        result = _read(result_path)
        scenario_id = result["scenario_id"]
        if scenario_id not in scenarios:
            raise RuntimeError("Generation result references an unknown frozen scenario")
        seen: set[tuple[str, ...]] = set()
        selected = []
        for proposal in result.get("proposals") or []:
            if not proposal.get("valid"):
                continue
            signature = tuple(sorted(proposal["item_ids"]))
            if signature in seen:
                continue
            if any(item_id not in items for item_id in proposal["item_ids"]):
                raise RuntimeError("Proposal references an item outside the frozen suite")
            seen.add(signature)
            selected.append(proposal)
            if len(selected) >= max_outfits_per_scenario:
                break
        for index, proposal in enumerate(selected, 1):
            outfits.append({
                "outfit_id": f"{scenario_id}-O{index:02d}",
                "scenario_id": scenario_id,
                "anchor_item_id": scenarios[scenario_id]["anchor_item_id"],
                "item_ids": proposal["item_ids"],
                "generation_reason": proposal.get("reason") or "",
                "source_model": source_manifest["model"],
            })
    if not outfits:
        raise RuntimeError("No hard-rule-valid generated outfits were available")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"composite-suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    prompt = _prompt()
    write_json_atomic(suite_dir / "items.json", items)
    write_json_atomic(suite_dir / "outfits.json", outfits)
    write_json_atomic(suite_dir / "output_schema.json", CompositeReviewBatch.model_json_schema())
    (suite_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(suite_dir / "suite_manifest.json", {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "generation_suite": generation_manifest["suite_id"],
        "source_run": str(source_run.resolve()),
        "source_model": source_manifest["model"],
        "outfit_count": len(outfits),
        "scenario_count": len({row["scenario_id"] for row in outfits}),
        "max_outfits_per_scenario": max_outfits_per_scenario,
        "outfits_per_visual_call": OUTFITS_PER_CALL,
        "planned_visual_calls": sum(
            math.ceil(count / OUTFITS_PER_CALL)
            for count in __import__("collections").Counter(
                row["scenario_id"] for row in outfits
            ).values()
        ),
        "composite_preprocessing": {
            "max_dimension": composite_max_dimension,
            "format": "JPEG",
            "quality": JPEG_QUALITY,
            "maximum_images_sent_per_call": OUTFITS_PER_CALL,
        },
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "items_sha256": digest(items),
        "outfits_sha256": digest(outfits),
        "output_schema_sha256": digest(CompositeReviewBatch.model_json_schema()),
        "safety": {"production_writes": False, "signed_image_urls_persisted": False},
    })
    return suite_dir


def _download_item_image(
    item: ClothingItemRecord, storage: StorageService, client: httpx.Client, timeout: float,
) -> Image.Image:
    signed_url = storage.signed_image_url(item.image_path, expires_in=900)
    if not signed_url or not signed_url.startswith("https://"):
        raise RuntimeError(f"Image unavailable for frozen item {item.id}")
    response = client.get(signed_url, timeout=timeout)
    response.raise_for_status()
    image = Image.open(io.BytesIO(response.content))
    image.load()
    return image


def _parse_batch(text: str, expected_ids: list[str]) -> CompositeReviewBatch:
    parsed = CompositeReviewBatch.model_validate_json(text)
    actual_ids = [review.outfit_id for review in parsed.reviews]
    if actual_ids != expected_ids:
        raise ValueError("Composite review must contain every supplied outfit exactly once and in order")
    return parsed


def run_composite_model(
    *, suite_dir: Path, model: str, base_url: str, protocol: str, schema_mode: str,
    api_key_env: str, timeout: float, input_rate: float, cached_rate: float,
    output_rate: float, budget: float, max_calls: int = 0,
    resume_run_dir: Path | None = None,
) -> Path:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing provider key in {api_key_env}")
    manifest = _read(suite_dir / "suite_manifest.json")
    items_doc = _read(suite_dir / "items.json")
    outfits = _read(suite_dir / "outfits.json")
    prompt = (suite_dir / "prompt.txt").read_text(encoding="utf-8")
    if digest(items_doc) != manifest["items_sha256"] or digest(outfits) != manifest["outfits_sha256"]:
        raise RuntimeError("Frozen composite suite checksum mismatch")
    if hashlib.sha256(prompt.encode()).hexdigest() != manifest["prompt_sha256"]:
        raise RuntimeError("Frozen composite prompt checksum mismatch")

    by_scenario: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for outfit in outfits:
        by_scenario[outfit["scenario_id"]].append(outfit)
    batches = [
        batch for scenario_id in sorted(by_scenario)
        for batch in _chunks(by_scenario[scenario_id])
    ]
    gateway = _gateway(protocol, base_url=base_url, api_key=api_key, schema_mode=schema_mode)
    storage = StorageService()
    client = httpx.Client(http2=False)
    rates = {"input": input_rate, "cached_input": cached_rate, "output": output_rate}
    run_dir = (
        resume_run_dir.resolve() if resume_run_dir is not None
        else suite_dir / "runs" / f"{model.replace('/', '--')}-{uuid4().hex[:8]}"
    )
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    existing_manifest = (
        _read(run_dir / "run_manifest.json")
        if (run_dir / "run_manifest.json").exists() else {}
    )
    if existing_manifest and (
        existing_manifest.get("suite_id") != manifest["suite_id"]
        or existing_manifest.get("model") != model
        or existing_manifest.get("schema_mode") != STRICT_SCHEMA_MODE
    ):
        raise RuntimeError("Resume run does not match the frozen suite, model and strict schema mode")
    existing_results = [
        _read(path) for path in (run_dir / "results").glob("*.json")
    ]
    spent = sum(float(row.get("estimated_cost_usd") or 0) for row in existing_results)
    max_dimension = int(manifest["composite_preprocessing"]["max_dimension"])
    attempted = 0
    for call_index, batch in enumerate(batches, 1):
        result_path = run_dir / "results" / f"{batch[0]['scenario_id']}-B{call_index:03d}.json"
        if result_path.exists() and _read(result_path).get("status") == "succeeded":
            continue
        if max_calls and attempted >= max_calls:
            break
        if spent >= budget:
            break
        attempted += 1
        outfit_ids = [outfit["outfit_id"] for outfit in batch]
        content: list[dict[str, Any]] = [{
            "type": "input_text",
            "text": json.dumps({"outfits": batch}),
        }]
        composite_audits = []
        for outfit in batch:
            members = [ClothingItemRecord.model_validate(items_doc[item_id]) for item_id in outfit["item_ids"]]
            metadata = [{field: getattr(item, field) for field in ITEM_METADATA_FIELDS} for item in members]
            content.append({
                "type": "input_text",
                "text": json.dumps({"outfit_id": outfit["outfit_id"], "items": metadata}, default=str),
            })
            source_images = [
                (item, _download_item_image(item, storage, client, timeout))
                for item in members
            ]
            composite, audit = _compose_outfit_image(source_images, max_dimension=max_dimension)
            composite_audits.append({"outfit_id": outfit["outfit_id"], **audit})
            content.append({
                "type": "input_image", "image_url": composite, "detail": "high",
            })

        started = time.perf_counter()
        result_doc: dict[str, Any] = {
            "call_index": call_index,
            "scenario_id": batch[0]["scenario_id"],
            "outfit_ids": outfit_ids,
            "status": "failed",
        }
        try:
            response = gateway.response(
                model=model,
                timeout=timeout,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": content},
                ],
                schema=_batch_schema(outfit_ids),
                schema_name="outfit_composite_visual_review",
            )
            usage = _usage(response.payload)
            cost = _estimated_cost(usage, rates)
            spent += cost
            review_batch = _parse_batch(response.text, outfit_ids)
            result_doc.update(
                status="succeeded",
                model_call_succeeded=True,
                latency_seconds=round(time.perf_counter() - started, 6),
                usage=usage,
                estimated_cost_usd=cost,
                raw_response=response.payload,
                raw_response_text=response.text,
                composite_preprocessing=composite_audits,
                reviews=[review.model_dump(mode="json") for review in review_batch.reviews],
            )
        except Exception as error:
            result_doc.update(
                latency_seconds=round(time.perf_counter() - started, 6),
                error={
                    "type": type(error).__name__,
                    "http_status": getattr(error, "http_status", None),
                    "provider_code": getattr(error, "provider_code", None),
                    "provider_message": getattr(error, "provider_message", None),
                    "message": str(error)[:1000],
                },
            )
        write_json_atomic(result_path, result_doc)

    write_json_atomic(run_dir / "run_manifest.json", {
        **existing_manifest,
        "schema_version": SCHEMA_VERSION,
        "suite_id": manifest["suite_id"],
        "model": model,
        "base_url": base_url,
        "protocol": protocol,
        "schema_mode": schema_mode,
        "outfits_per_visual_call": OUTFITS_PER_CALL,
        "pricing_usd_per_million": rates,
        "budget_usd": budget,
        "production_writes": False,
        "created_at": existing_manifest.get("created_at") or utc_now(),
        "last_resumed_at": utc_now() if existing_manifest else None,
    })
    summarize(run_dir)
    return run_dir


def summarize(run_dir: Path) -> dict[str, Any]:
    calls = [_read(path) for path in sorted((run_dir / "results").glob("*.json"))]
    succeeded = [call for call in calls if call.get("status") == "succeeded"]
    reviews = [review for call in succeeded for review in call.get("reviews", [])]
    criteria = ("physical_fit", "style_silhouette", "color_pattern", "thermal_occasion")
    outfit_rows = []
    for review in reviews:
        verdicts = [review[criterion]["verdict"] for criterion in criteria]
        verdict = "fail" if "fail" in verdicts else "uncertain" if "uncertain" in verdicts else "pass"
        outfit_rows.append({"outfit_id": review["outfit_id"], "model_verdict": verdict})
    latencies = [float(call["latency_seconds"]) for call in succeeded]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "visual_calls_completed": len(calls),
        "visual_call_success_rate": len(succeeded) / len(calls) if calls else None,
        "outfits_reviewed": len(outfit_rows),
        "outfit_pass_rate": (
            sum(row["model_verdict"] == "pass" for row in outfit_rows) / len(outfit_rows)
            if outfit_rows else None
        ),
        "outfit_verdict_counts": {
            verdict: sum(row["model_verdict"] == verdict for row in outfit_rows)
            for verdict in ("pass", "fail", "uncertain")
        },
        "latency_seconds": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "usage": {
            key: sum((call.get("usage") or {}).get(key, 0) for call in calls)
            for key in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        "estimated_cost_usd": sum(float(call.get("estimated_cost_usd") or 0) for call in calls),
    }
    write_json_atomic(run_dir / "summary.json", summary)
    write_json_atomic(run_dir / "outfit_results.json", outfit_rows)
    with (run_dir / "annotation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "outfit_id", "model_verdict", "human_physically_wearable_yes_no",
            "human_aesthetic_1_5", "human_would_wear_yes_no", "reviewer_notes",
        ))
        writer.writeheader()
        writer.writerows(outfit_rows)
    return summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--generation-suite", type=Path, required=True)
    prepare.add_argument("--source-run", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path, required=True)
    prepare.add_argument("--max-outfits-per-scenario", type=int, default=DEFAULT_OUTFITS_PER_ANCHOR)
    prepare.add_argument("--composite-max-dimension", type=int, default=1024)
    run = commands.add_parser("run")
    run.add_argument("--suite-dir", type=Path, required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--base-url", required=True)
    run.add_argument("--protocol", choices=("responses", "chat-completions"), required=True)
    run.add_argument("--schema-mode", choices=(STRICT_SCHEMA_MODE,), default=STRICT_SCHEMA_MODE)
    run.add_argument("--api-key-env", required=True)
    run.add_argument("--timeout", type=float, default=180)
    run.add_argument("--input-rate", type=float, required=True)
    run.add_argument("--cached-rate", type=float, required=True)
    run.add_argument("--output-rate", type=float, required=True)
    run.add_argument("--budget", type=float, default=1)
    run.add_argument("--max-calls", type=int, default=0)
    run.add_argument("--resume-run-dir", type=Path)
    summary = commands.add_parser("summarize")
    summary.add_argument("--run-dir", type=Path, required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        path = prepare_composite_suite(
            generation_suite=args.generation_suite.resolve(),
            source_run=args.source_run.resolve(),
            output_root=args.output_root,
            max_outfits_per_scenario=args.max_outfits_per_scenario,
            composite_max_dimension=args.composite_max_dimension,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "run":
        path = run_composite_model(
            suite_dir=args.suite_dir.resolve(), model=args.model,
            base_url=args.base_url, protocol=args.protocol,
            schema_mode=args.schema_mode, api_key_env=args.api_key_env,
            timeout=args.timeout, input_rate=args.input_rate,
            cached_rate=args.cached_rate, output_rate=args.output_rate,
            budget=args.budget, max_calls=args.max_calls,
            resume_run_dir=args.resume_run_dir,
        )
        print(json.dumps({
            "state": "complete", "run_dir": str(path), "summary": summarize(path),
        }, indent=2))
    else:
        print(json.dumps(summarize(args.run_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
