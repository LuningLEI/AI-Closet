"""Read-only two-image visual review for metadata-generated Outfit proposals."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import ClothingItemRecord
from app.outfits.compatibility import slot
from app.services.storage_service import StorageService
from tools.evaluation.outfit_model_shadow import (
    STRICT_SCHEMA_MODE,
    _estimated_cost,
    _gateway,
    _usage,
)
from tools.evaluation.outfit_visual_shadow import ITEM_METADATA_FIELDS
from tools.evaluation.recognition_shadow import (
    _redact_request_image,
    _resized_image_input,
    digest,
    write_json_atomic,
)


SCHEMA_VERSION = "outfit-pairwise-visual-shadow-v1"


class PairCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["pass", "fail", "uncertain"]
    reason: str = Field(min_length=1)


class PairVisualReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    physical_fit: PairCriterion
    style_silhouette: PairCriterion
    color_pattern: PairCriterion
    thermal_occasion: PairCriterion


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _prompt() -> str:
    return """You are the pairwise visual compatibility gate in an outfit recommendation system.
Judge only the supplied target pair (or the one supplied garment for a single-item outfit), while using the full outfit metadata as context.

The photos are authoritative for visible silhouette, sportiness, formality, bulk, drape, pattern and color. Metadata is supporting evidence and must not override a visible conflict. A structurally legal pair can still fail aesthetically. For example, an athletic performance T-shirt with an elegant draped maxi skirt should fail style_silhouette even when both metadata records say Casual or Everyday.

physical_fit: Can the garments physically be worn together, including layering capacity, coverage and competing volume?
style_silhouette: Do sportiness, formality, cut, drape, proportions and visual weight form an intentional outfit?
color_pattern: Are the visible colors and patterns coherent rather than merely non-identical?
thermal_occasion: Do warmth, exposure, purpose and occasion make sense together?

Return only one JSON object with exactly physical_fit, style_silhouette, color_pattern and thermal_occasion. Each value must be an object with verdict pass|fail|uncertain and a concrete image-grounded reason. Use uncertain when the flat-lay photo cannot support a reliable judgment. Do not rationalize a conflict just because broad metadata tags overlap."""


def _pairs(item_ids: list[str]) -> list[list[str]]:
    if len(item_ids) == 1:
        return [item_ids]
    return [list(pair) for pair in itertools.combinations(item_ids, 2)]


def prepare_pairwise_suite(
    *, generation_suite: Path, source_run: Path, output_root: Path,
    max_outfits_per_scenario: int = 5, image_max_dimension: int = 768,
) -> Path:
    if max_outfits_per_scenario < 1 or image_max_dimension < 1:
        raise ValueError("max-outfits-per-scenario and image-max-dimension must be positive")
    generation_manifest = _read(generation_suite / "suite_manifest.json")
    run_manifest = _read(source_run / "run_manifest.json")
    items = _read(generation_suite / "items.json")
    scenarios = {row["scenario_id"]: row for row in _read(generation_suite / "scenarios.json")}
    outfits: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    for result_path in sorted((source_run / "results").glob("*.json")):
        result = _read(result_path)
        scenario_id = result["scenario_id"]
        scenario = scenarios[scenario_id]
        accepted = [row for row in result.get("proposals") or [] if row.get("valid")]
        seen: set[tuple[str, ...]] = set()
        selected = []
        for proposal in accepted:
            signature = tuple(sorted(proposal["item_ids"]))
            if signature in seen:
                continue
            if any(item_id not in items for item_id in proposal["item_ids"]):
                raise RuntimeError("Proposal references an item outside the frozen suite")
            seen.add(signature)
            selected.append(proposal)
            if len(selected) >= max_outfits_per_scenario:
                break
        for proposal_index, proposal in enumerate(selected, 1):
            outfit_id = f"{scenario_id}-O{proposal_index:02d}"
            outfit = {
                "outfit_id": outfit_id,
                "scenario_id": scenario_id,
                "anchor_item_id": scenario["anchor_item_id"],
                "item_ids": proposal["item_ids"],
                "generation_reason": proposal.get("reason") or "",
                "source_model": run_manifest["model"],
            }
            outfits.append(outfit)
            for pair_index, pair_ids in enumerate(_pairs(proposal["item_ids"]), 1):
                pair_slots = [slot(ClothingItemRecord.model_validate(items[item_id])) for item_id in pair_ids]
                pairs.append({
                    "pair_id": f"{outfit_id}-P{pair_index:02d}",
                    "outfit_id": outfit_id,
                    "target_item_ids": pair_ids,
                    "full_outfit_item_ids": proposal["item_ids"],
                    "pair_role": "single_item" if len(pair_ids) == 1 else "-".join(pair_slots),
                })
    if not outfits:
        raise RuntimeError("No hard-rule-valid metadata-generated outfits were available")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"pairwise-suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    prompt = _prompt()
    write_json_atomic(suite_dir / "items.json", items)
    write_json_atomic(suite_dir / "outfits.json", outfits)
    write_json_atomic(suite_dir / "pairs.json", pairs)
    write_json_atomic(suite_dir / "output_schema.json", PairVisualReview.model_json_schema())
    (suite_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(suite_dir / "suite_manifest.json", {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "generation_suite": generation_manifest["suite_id"],
        "source_run": str(source_run.resolve()),
        "source_model": run_manifest["model"],
        "outfit_count": len(outfits),
        "pair_count": len(pairs),
        "max_outfits_per_scenario": max_outfits_per_scenario,
        "image_preprocessing": {"max_dimension": image_max_dimension, "format": "JPEG", "quality": 90},
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "items_sha256": digest(items),
        "outfits_sha256": digest(outfits),
        "pairs_sha256": digest(pairs),
        "safety": {"production_writes": False, "max_images_per_request": 2},
    })
    return suite_dir


def _parse_review(text: str) -> PairVisualReview:
    return PairVisualReview.model_validate_json(text)


def run_pairwise_model(
    *, suite_dir: Path, model: str, base_url: str, protocol: str, schema_mode: str,
    api_key_env: str, timeout: float, input_rate: float, cached_rate: float,
    output_rate: float, budget: float, max_pairs: int = 0,
) -> Path:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing provider key in {api_key_env}")
    manifest = _read(suite_dir / "suite_manifest.json")
    items_doc = _read(suite_dir / "items.json")
    outfits = {row["outfit_id"]: row for row in _read(suite_dir / "outfits.json")}
    pairs = _read(suite_dir / "pairs.json")
    prompt = (suite_dir / "prompt.txt").read_text(encoding="utf-8")
    schema = _read(suite_dir / "output_schema.json")
    if digest(items_doc) != manifest["items_sha256"] or digest(pairs) != manifest["pairs_sha256"]:
        raise RuntimeError("Frozen pairwise suite checksum mismatch")
    gateway = _gateway(protocol, base_url=base_url, api_key=api_key, schema_mode=schema_mode)
    storage = StorageService()
    client = httpx.Client(http2=False)
    rates = {"input": input_rate, "cached_input": cached_rate, "output": output_rate}
    run_dir = suite_dir / "runs" / f"{model.replace('/', '--')}-{uuid4().hex[:8]}"
    (run_dir / "results").mkdir(parents=True)
    spent = 0.0
    max_dimension = int(manifest["image_preprocessing"]["max_dimension"])
    for pair in pairs[:max_pairs or None]:
        if spent >= budget:
            break
        outfit = outfits[pair["outfit_id"]]
        target = set(pair["target_item_ids"])
        content: list[dict[str, Any]] = [{
            "type": "input_text",
            "text": json.dumps({"pair": pair, "outfit": outfit}),
        }]
        request_images: list[tuple[str, str]] = []
        image_audits = []
        for item_id in pair["full_outfit_item_ids"]:
            item = ClothingItemRecord.model_validate(items_doc[item_id])
            content.append({
                "type": "input_text",
                "text": json.dumps({
                    "visual_target": item_id in target,
                    **{field: getattr(item, field) for field in ITEM_METADATA_FIELDS},
                }, default=str),
            })
            if item_id not in target:
                continue
            signed_url = storage.signed_image_url(item.image_path, expires_in=900)
            if not signed_url or not signed_url.startswith("https://"):
                raise RuntimeError(f"Image unavailable for frozen item {item.id}")
            request_image, audit = _resized_image_input(
                signed_url, max_dimension=max_dimension, client=client, timeout=timeout,
            )
            request_images.append((request_image, signed_url))
            image_audits.append({"item_id": item.id, **audit})
            content.append({"type": "input_image", "image_url": request_image, "detail": "low"})
        started = time.perf_counter()
        result_doc: dict[str, Any] = {"pair_id": pair["pair_id"], "source": pair, "status": "failed"}
        try:
            response = gateway.response(
                model=model, timeout=timeout,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": content},
                ],
                schema=schema, schema_name="outfit_pairwise_visual_review",
            )
            usage = _usage(response.payload)
            cost = _estimated_cost(usage, rates)
            spent += cost
            raw_payload: Any = response.payload
            raw_text: Any = response.text
            for request_image, signed_url in request_images:
                raw_payload = _redact_request_image(raw_payload, request_image, signed_url)
                raw_text = _redact_request_image(raw_text, request_image, signed_url)
            review = _parse_review(response.text)
            result_doc.update(
                status="succeeded",
                model_call_succeeded=True,
                latency_seconds=round(time.perf_counter() - started, 6),
                usage=usage,
                estimated_cost_usd=cost,
                raw_response=raw_payload,
                raw_response_text=raw_text,
                image_preprocessing=image_audits,
                review=review.model_dump(mode="json"),
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
        write_json_atomic(run_dir / "results" / f"{pair['pair_id']}.json", result_doc)
    write_json_atomic(run_dir / "run_manifest.json", {
        "schema_version": SCHEMA_VERSION,
        "suite_id": manifest["suite_id"],
        "model": model,
        "base_url": base_url,
        "protocol": protocol,
        "schema_mode": schema_mode,
        "pricing_usd_per_million": rates,
        "budget_usd": budget,
        "production_writes": False,
        "created_at": utc_now(),
    })
    summarize(run_dir)
    return run_dir


def summarize(run_dir: Path) -> dict[str, Any]:
    results = [_read(path) for path in sorted((run_dir / "results").glob("*.json"))]
    succeeded = [row for row in results if row.get("status") == "succeeded"]
    by_outfit: dict[str, list[dict[str, Any]]] = {}
    for row in succeeded:
        by_outfit.setdefault(row["source"]["outfit_id"], []).append(row)
    outfit_rows = []
    criteria = ("physical_fit", "style_silhouette", "color_pattern", "thermal_occasion")
    for outfit_id, rows in sorted(by_outfit.items()):
        verdicts = [row["review"][criterion]["verdict"] for row in rows for criterion in criteria]
        verdict = "fail" if "fail" in verdicts else "uncertain" if "uncertain" in verdicts else "pass"
        outfit_rows.append({"outfit_id": outfit_id, "pair_count": len(rows), "model_verdict": verdict})
    latencies = [float(row["latency_seconds"]) for row in succeeded]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "pairs_completed": len(results),
        "pair_success_rate": len(succeeded) / len(results) if results else None,
        "outfits_reviewed": len(outfit_rows),
        "outfit_pass_rate": sum(row["model_verdict"] == "pass" for row in outfit_rows) / len(outfit_rows) if outfit_rows else None,
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
            key: sum((row.get("usage") or {}).get(key, 0) for row in results)
            for key in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        "estimated_cost_usd": sum(float(row.get("estimated_cost_usd") or 0) for row in results),
    }
    write_json_atomic(run_dir / "summary.json", summary)
    write_json_atomic(run_dir / "outfit_results.json", outfit_rows)
    with (run_dir / "annotation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "outfit_id", "model_verdict", "pair_count", "human_physically_wearable_yes_no",
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
    prepare.add_argument("--max-outfits-per-scenario", type=int, default=5)
    prepare.add_argument("--image-max-dimension", type=int, default=768)
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
    run.add_argument("--budget", type=float, default=1)
    run.add_argument("--max-pairs", type=int, default=0)
    summary = commands.add_parser("summarize")
    summary.add_argument("--run-dir", type=Path, required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        path = prepare_pairwise_suite(
            generation_suite=args.generation_suite.resolve(),
            source_run=args.source_run.resolve(),
            output_root=args.output_root,
            max_outfits_per_scenario=args.max_outfits_per_scenario,
            image_max_dimension=args.image_max_dimension,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "run":
        path = run_pairwise_model(
            suite_dir=args.suite_dir.resolve(), model=args.model, base_url=args.base_url,
            protocol=args.protocol, schema_mode=args.schema_mode, api_key_env=args.api_key_env,
            timeout=args.timeout, input_rate=args.input_rate, cached_rate=args.cached_rate,
            output_rate=args.output_rate, budget=args.budget, max_pairs=args.max_pairs,
        )
        print(json.dumps({"state": "complete", "run_dir": str(path), "summary": summarize(path)}, indent=2))
    else:
        print(json.dumps(summarize(args.run_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
