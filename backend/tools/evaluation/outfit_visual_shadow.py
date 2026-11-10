"""Paired, read-only visual-review evaluation for frozen outfit proposals."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.models.domain import ClothingItemRecord
from app.outfits.config import load_config
from app.outfits.models import CurrentVisualReview
from app.services.storage_service import StorageService
from tools.evaluation.outfit_model_shadow import (
    STRICT_SCHEMA_MODE,
    _estimated_cost,
    _gateway,
    _usage,
)
from tools.evaluation.recognition_shadow import (
    _redact_request_image,
    _resized_image_input,
    digest,
    write_json_atomic,
)


SCHEMA_VERSION = "outfit-visual-shadow-v1"
ITEM_METADATA_FIELDS = (
    "id", "category", "subtype", "color", "style", "material", "pattern", "fit",
    "length", "sleeve_length", "layering_role", "wearing_profile", "color_tones",
    "warmth_level", "formality_score", "occasion", "season",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _visual_prompt(prompt: str) -> str:
    return f"""{prompt.rstrip()}

MANDATORY OUTPUT CONTRACT:
- Return only one JSON object with exactly these top-level keys: core, full, optional_layering.
- core and full must each contain exactly wearability, thermal, color_pattern, occasion.
- Every criterion value MUST be an object shaped as {{"verdict":"pass|fail|uncertain","reason":"concrete item-specific explanation"}}. Never use a bare string such as "pass".
- optional_layering MUST be an object shaped as {{"verdict":"clear_improvement|no_improvement|uncertain|not_applicable","reason":"explanation"}}. It is still required when no optional layer exists; use not_applicable then.
- When core_item_ids and full_item_ids are identical, core and full verdicts and reasons must agree.
- Do not omit reasons, keys, or optional_layering. Silently verify the complete nested shape before returning JSON.
"""


def prepare_visual_suite(
    *, generation_suite: Path, source_runs: list[Path], limit: int, output_root: Path,
    image_max_dimension: int = 768,
) -> Path:
    if limit < 1 or image_max_dimension < 1:
        raise ValueError("limit and image-max-dimension must be positive")
    generation_manifest = _read(generation_suite / "suite_manifest.json")
    items = _read(generation_suite / "items.json")
    scenarios = {row["scenario_id"]: row for row in _read(generation_suite / "scenarios.json")}
    pools: list[list[dict[str, Any]]] = []
    source_manifests = []
    for source_run in source_runs:
        run_manifest = _read(source_run / "run_manifest.json")
        source_manifests.append({
            "run_dir": str(source_run.resolve()),
            "model": run_manifest["model"],
        })
        rows_by_scenario: dict[str, list[dict[str, Any]]] = {}
        for result_path in sorted((source_run / "results").glob("*.json")):
            result = _read(result_path)
            for proposal_index, proposal in enumerate(result.get("proposals") or [], 1):
                if not proposal.get("valid"):
                    continue
                rows_by_scenario.setdefault(result["scenario_id"], []).append({
                    "source_model": run_manifest["model"],
                    "source_scenario_id": result["scenario_id"],
                    "source_proposal_index": proposal_index,
                    "item_ids": proposal["item_ids"],
                })
        rows = []
        maximum = max((len(values) for values in rows_by_scenario.values()), default=0)
        for proposal_offset in range(maximum):
            for scenario_id in sorted(rows_by_scenario):
                scenario_rows = rows_by_scenario[scenario_id]
                if proposal_offset < len(scenario_rows):
                    rows.append(scenario_rows[proposal_offset])
        pools.append(rows)

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    cursors = [0] * len(pools)
    while len(selected) < limit:
        progressed = False
        for pool_index, pool in enumerate(pools):
            while cursors[pool_index] < len(pool):
                row = pool[cursors[pool_index]]
                cursors[pool_index] += 1
                signature = tuple(sorted(row["item_ids"]))
                if signature in seen:
                    continue
                if any(item_id not in items for item_id in row["item_ids"]):
                    raise RuntimeError("A review proposal references an item outside the frozen suite")
                seen.add(signature)
                selected.append(row)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break
    if not selected:
        raise RuntimeError("No valid generated proposals were available for visual review")

    reviews = []
    for index, row in enumerate(selected, 1):
        scenario = scenarios[row["source_scenario_id"]]
        reviews.append({
            "review_id": f"V{index:03d}",
            **row,
            "anchor_item_id": scenario["anchor_item_id"],
            "request": {
                "require_shoes": False,
                "core_item_ids": row["item_ids"],
                "full_item_ids": row["item_ids"],
                "optional_layer_item_ids": [],
            },
        })

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suite_dir = output_root.resolve() / f"visual-suite-{timestamp}-{uuid4().hex[:8]}"
    suite_dir.mkdir(parents=True)
    prompt_text = _visual_prompt(load_config().evaluation_text)
    (suite_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    write_json_atomic(suite_dir / "items.json", items)
    write_json_atomic(suite_dir / "reviews.json", reviews)
    write_json_atomic(suite_dir / "output_schema.json", CurrentVisualReview.model_json_schema())
    write_json_atomic(suite_dir / "suite_manifest.json", {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite_dir.name,
        "created_at": utc_now(),
        "generation_suite": generation_manifest["suite_id"],
        "source_runs": source_manifests,
        "review_count": len(reviews),
        "image_preprocessing": {
            "max_dimension": image_max_dimension,
            "format": "JPEG",
            "quality": 90,
        },
        "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
        "items_sha256": digest(items),
        "reviews_sha256": digest(reviews),
        "output_schema_sha256": digest(CurrentVisualReview.model_json_schema()),
        "safety": {"production_writes": False, "signed_image_urls_persisted": False},
    })
    return suite_dir


def _parse_review(text: str) -> tuple[CurrentVisualReview, list[str], bool]:
    try:
        return CurrentVisualReview.model_validate_json(text), [], True
    except Exception as original_error:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            raise original_error
        if isinstance(payload, dict) and isinstance(payload.get("review"), dict):
            return CurrentVisualReview.model_validate(payload["review"]), ["unwrap_review"], False
        raise original_error


def run_visual_model(
    *, suite_dir: Path, model: str, base_url: str, protocol: str, schema_mode: str,
    api_key_env: str, timeout: float, input_rate: float, cached_rate: float,
    output_rate: float, budget: float, max_reviews: int = 0,
) -> Path:
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing provider key in {api_key_env}")
    manifest = _read(suite_dir / "suite_manifest.json")
    items_doc = _read(suite_dir / "items.json")
    reviews = _read(suite_dir / "reviews.json")
    prompt = (suite_dir / "prompt.txt").read_text(encoding="utf-8")
    schema = _read(suite_dir / "output_schema.json")
    if digest(items_doc) != manifest["items_sha256"] or digest(reviews) != manifest["reviews_sha256"]:
        raise RuntimeError("Frozen visual-review suite checksum mismatch")
    if hashlib.sha256(prompt.encode()).hexdigest() != manifest["prompt_sha256"]:
        raise RuntimeError("Frozen visual-review prompt checksum mismatch")

    gateway = _gateway(protocol, base_url=base_url, api_key=api_key, schema_mode=schema_mode)
    storage = StorageService()
    client = httpx.Client(http2=False)
    rates = {"input": input_rate, "cached_input": cached_rate, "output": output_rate}
    run_dir = suite_dir / "runs" / f"{model.replace('/', '--')}-{uuid4().hex[:8]}"
    (run_dir / "results").mkdir(parents=True)
    spent = 0.0
    max_dimension = int(manifest["image_preprocessing"]["max_dimension"])
    for review in reviews[:max_reviews or None]:
        if spent >= budget:
            break
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": json.dumps(review["request"])},
        ]
        request_images: list[tuple[str, str]] = []
        image_audits = []
        for item_id in review["item_ids"]:
            item = ClothingItemRecord.model_validate(items_doc[item_id])
            content.append({
                "type": "input_text",
                "text": json.dumps({
                    field: getattr(item, field) for field in ITEM_METADATA_FIELDS
                }, default=str),
            })
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
        result_doc: dict[str, Any] = {
            "review_id": review["review_id"], "status": "failed", "source": review,
        }
        try:
            response = gateway.response(
                model=model,
                timeout=timeout,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                    {"role": "user", "content": content},
                ],
                schema=schema,
                schema_name="outfit_visual_review",
            )
            usage = _usage(response.payload)
            cost = _estimated_cost(usage, rates)
            spent += cost
            raw_payload: Any = response.payload
            raw_text: Any = response.text
            for request_image, signed_url in request_images:
                raw_payload = _redact_request_image(raw_payload, request_image, signed_url)
                raw_text = _redact_request_image(raw_text, request_image, signed_url)
            result_doc.update(
                model_call_succeeded=True,
                usage=usage,
                estimated_cost_usd=cost,
                raw_response=raw_payload,
                raw_response_text=raw_text,
                image_preprocessing=image_audits,
            )
            parsed, actions, raw_valid = _parse_review(response.text)
            result_doc.update(
                status="succeeded",
                latency_seconds=round(time.perf_counter() - started, 6),
                raw_contract_valid=raw_valid,
                text_repair_actions=actions,
                review=parsed.model_dump(mode="json"),
            )
        except Exception as error:
            result_doc.update(
                latency_seconds=round(time.perf_counter() - started, 6),
                error={"type": type(error).__name__, "message": str(error)[:1000]},
            )
        write_json_atomic(run_dir / "results" / f"{review['review_id']}.json", result_doc)

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
    latencies = [float(row["latency_seconds"]) for row in succeeded]
    criteria = ("wearability", "thermal", "color_pattern", "occasion")
    criterion_counts = {
        scope: {
            criterion: {
                verdict: sum(
                    row["review"][scope][criterion]["verdict"] == verdict for row in succeeded
                )
                for verdict in ("pass", "fail", "uncertain")
            }
            for criterion in criteria
        }
        for scope in ("core", "full")
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "reviews_completed": len(results),
        "review_success_rate": len(succeeded) / len(results) if results else None,
        "core_all_pass_rate": sum(
            all(row["review"]["core"][name]["verdict"] == "pass" for name in criteria)
            for row in succeeded
        ) / len(succeeded) if succeeded else None,
        "criterion_counts": criterion_counts,
        "latency_seconds": {
            "mean": statistics.fmean(latencies) if latencies else None,
            "p50": statistics.median(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "usage": {
            key: sum((row.get("usage") or {}).get(key, 0) for row in results)
            for key in ("input_tokens", "cached_input_tokens", "output_tokens")
        },
        "estimated_cost_usd": sum(
            float(row.get("estimated_cost_usd") or 0) for row in results
        ),
    }
    write_json_atomic(run_dir / "summary.json", summary)
    with (run_dir / "annotation.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "review_id", "source_model", "item_ids", "model_core_all_pass",
            "human_physically_wearable_yes_no", "human_looks_compatible_1_5",
            "human_preferred_yes_no", "reviewer_notes",
        ))
        writer.writeheader()
        for row in succeeded:
            core = row["review"]["core"]
            writer.writerow({
                "review_id": row["review_id"],
                "source_model": row["source"]["source_model"],
                "item_ids": " | ".join(row["source"]["item_ids"]),
                "model_core_all_pass": all(
                    core[name]["verdict"] == "pass" for name in criteria
                ),
            })
    return summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--generation-suite", type=Path, required=True)
    prepare.add_argument("--source-run", type=Path, action="append", required=True)
    prepare.add_argument("--limit", type=int, default=10)
    prepare.add_argument("--image-max-dimension", type=int, default=768)
    prepare.add_argument("--output-root", type=Path, required=True)
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
    run.add_argument("--max-reviews", type=int, default=0)
    summary = commands.add_parser("summarize")
    summary.add_argument("--run-dir", type=Path, required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "prepare":
        path = prepare_visual_suite(
            generation_suite=args.generation_suite.resolve(),
            source_runs=[path.resolve() for path in args.source_run],
            limit=args.limit,
            output_root=args.output_root,
            image_max_dimension=args.image_max_dimension,
        )
        print(json.dumps({"state": "prepared", "suite_dir": str(path)}, indent=2))
    elif args.command == "run":
        path = run_visual_model(
            suite_dir=args.suite_dir.resolve(), model=args.model, base_url=args.base_url,
            protocol=args.protocol, schema_mode=args.schema_mode,
            api_key_env=args.api_key_env, timeout=args.timeout,
            input_rate=args.input_rate, cached_rate=args.cached_rate,
            output_rate=args.output_rate, budget=args.budget,
            max_reviews=args.max_reviews,
        )
        print(json.dumps({
            "state": "complete", "run_dir": str(path), "summary": summarize(path),
        }, indent=2))
    else:
        print(json.dumps(summarize(args.run_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
