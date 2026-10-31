"""Run a direct-vision outfit baseline outside the production recommendation API."""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import mimetypes
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.constants import (
    OPENAI_RESPONSES_TIMEOUT_SECONDS,
    OPENAI_RESPONSES_URL,
    RECOGNITION_EXCLUDED_SOURCES,
    VISION_IMAGE_URL_EXPIRES_SECONDS,
)
from app.models.domain import ClothingItemRecord
from app.repositories.factory import build_closet_repository
from app.services.storage_service import StorageService
from tools.evaluation.paths import evaluation_path


@dataclass(frozen=True)
class BaselineCandidate:
    code: str
    item_id: str
    title: str
    category: str
    color: str
    style: str
    occasion: str
    image_url: str


@dataclass(frozen=True)
class BaselineLook:
    look_number: int
    image_codes: list[str]
    styling_note: str


@dataclass(frozen=True)
class BaselineResult:
    run_id: str
    user_id: str
    model: str
    generated_at: str
    temperature_f: float
    occasion: str
    style: str
    requested_looks: int
    candidate_count: int
    latency_seconds: float
    recommendation_summary: str
    looks: list[BaselineLook]
    usage: dict[str, Any]


class DirectVisionBaseline:
    """Zero-shot visual baseline: no current retrieval or ranking logic is used."""

    def __init__(self, storage_service: StorageService | None = None) -> None:
        self.storage_service = storage_service or StorageService()

    def candidates_for_items(self, items: list[ClothingItemRecord], max_images: int) -> list[BaselineCandidate]:
        usable_items = [item for item in items if item.recognition_source not in RECOGNITION_EXCLUDED_SOURCES]
        if max_images > 0:
            usable_items = usable_items[:max_images]

        candidates: list[BaselineCandidate] = []
        for index, item in enumerate(usable_items, start=1):
            image_url = self._vision_image_url(item)
            if not image_url:
                continue
            candidates.append(
                BaselineCandidate(
                    code=f"I{index:03d}",
                    item_id=item.id,
                    title=item.subtype or item.category,
                    category=item.category,
                    color=item.color,
                    style=item.style,
                    occasion=item.occasion,
                    image_url=image_url,
                )
            )
        return candidates

    def run(
        self,
        *,
        user_id: str,
        candidates: list[BaselineCandidate],
        temperature_f: float,
        occasion: str,
        style: str,
        looks: int,
        model: str,
        detail: str,
        timeout_seconds: float,
        input_content: list[dict[str, str]] | None = None,
    ) -> tuple[BaselineResult, dict[str, Any]]:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required to run the direct-vision baseline.")
        if not candidates:
            raise RuntimeError("No eligible closet images were found for this user.")

        started_at = time.perf_counter()
        response = httpx.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "input": [{"role": "user", "content": input_content or self._input_content(candidates, temperature_f, occasion, style, looks, detail)}],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "wardrobe_outfit_recommendation",
                        "schema": self._response_schema([candidate.code for candidate in candidates], looks),
                        "strict": True,
                    }
                },
            },
            timeout=timeout_seconds,
        )
        if response.is_error:
            raise RuntimeError(
                f"OpenAI direct-vision baseline failed with HTTP {response.status_code}: {response.text}"
            )
        raw_response = response.json()
        parsed = self._parse_output(raw_response)
        result = self._result_from_output(
            parsed,
            user_id=user_id,
            model=model,
            temperature_f=temperature_f,
            occasion=occasion,
            style=style,
            requested_looks=looks,
            candidate_count=len(candidates),
            latency_seconds=time.perf_counter() - started_at,
            allowed_codes={candidate.code for candidate in candidates},
            usage=raw_response.get("usage") or {},
        )
        return result, raw_response

    def _vision_image_url(self, item: ClothingItemRecord) -> str | None:
        signed_url = self.storage_service.signed_image_url(item.image_path, expires_in=VISION_IMAGE_URL_EXPIRES_SECONDS)
        if signed_url and signed_url.startswith("https://"):
            return signed_url

        path = Path(item.image_path or "")
        if path.is_file():
            mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        return item.image_url if item.image_url.startswith("https://") else None

    def _input_content(
        self,
        candidates: list[BaselineCandidate],
        temperature_f: float,
        occasion: str,
        style: str,
        looks: int,
        detail: str,
    ) -> list[dict[str, str]]:
        prompt = f"""You are a personal wardrobe styling assistant.
The supplied closet photos are labelled with image codes. Create exactly {looks} distinct looks for:
- temperature: {temperature_f:g}F
- occasion: {occasion}
- preferred style: {style}

Inspect the photos yourself. Return only image codes from the supplied catalog; do not invent clothing, names, or codes. A look may use a dress or jumpsuit as its main garment, or one top plus a bottom. Outerwear and accessories are optional. Do not repeat an image code within a look. Use different main garments across looks when possible. Keep explanations concise and human-readable.
"""
        content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
        for candidate in candidates:
            content.append({"type": "input_text", "text": f"IMAGE CODE: {candidate.code}"})
            content.append({"type": "input_image", "image_url": candidate.image_url, "detail": detail})
        return content

    @staticmethod
    def _response_schema(image_codes: list[str], looks: int) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "recommendation_summary": {"type": "string"},
                "looks": {
                    "type": "array",
                    "minItems": looks,
                    "maxItems": looks,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "look_number": {"type": "integer", "minimum": 1, "maximum": looks},
                            "image_codes": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 5,
                                "items": {"type": "string", "enum": image_codes},
                            },
                            "styling_note": {"type": "string"},
                        },
                        "required": ["look_number", "image_codes", "styling_note"],
                    },
                },
            },
            "required": ["recommendation_summary", "looks"],
        }

    @staticmethod
    def _parse_output(payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("output_text")
        if not text:
            text = "\n".join(
                content["text"]
                for output in payload.get("output", [])
                for content in output.get("content", [])
                if content.get("type") in {"output_text", "text"} and content.get("text")
            )
        if not text:
            raise ValueError("The model response did not include structured output text.")
        return json.loads(text)

    @staticmethod
    def _result_from_output(
        output: dict[str, Any],
        *,
        user_id: str,
        model: str,
        temperature_f: float,
        occasion: str,
        style: str,
        requested_looks: int,
        candidate_count: int,
        latency_seconds: float,
        allowed_codes: set[str],
        usage: dict[str, Any],
    ) -> BaselineResult:
        looks: list[BaselineLook] = []
        for raw_look in output.get("looks", []):
            codes = [str(code) for code in raw_look.get("image_codes", [])]
            unknown_codes = sorted(set(codes) - allowed_codes)
            if unknown_codes:
                raise ValueError(f"The model returned unknown image codes: {', '.join(unknown_codes)}")
            if len(codes) != len(set(codes)):
                raise ValueError(f"Look {raw_look['look_number']} repeats an image code.")
            looks.append(BaselineLook(int(raw_look["look_number"]), codes, str(raw_look.get("styling_note") or "")))
        if len(looks) != requested_looks:
            raise ValueError(f"Expected {requested_looks} looks, received {len(looks)}.")
        if len({look.look_number for look in looks}) != len(looks):
            raise ValueError("The model returned duplicate look numbers.")
        return BaselineResult(
            run_id=str(uuid4()),
            user_id=user_id,
            model=model,
            generated_at=datetime.now(timezone.utc).isoformat(),
            temperature_f=temperature_f,
            occasion=occasion,
            style=style,
            requested_looks=requested_looks,
            candidate_count=candidate_count,
            latency_seconds=latency_seconds,
            recommendation_summary=str(output.get("recommendation_summary") or ""),
            looks=sorted(looks, key=lambda look: look.look_number),
            usage=usage,
        )


def write_artifacts(output_dir: Path, result: BaselineResult, candidates: list[BaselineCandidate], raw_response: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_by_code = {candidate.code: candidate for candidate in candidates}
    (output_dir / "raw_response.json").write_text(json.dumps(raw_response, indent=2), encoding="utf-8")
    (output_dir / "result.json").write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")

    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as file:
        fields = ["run_id", "user_id", "model", "generated_at", "temperature_f", "occasion", "style", "candidate_count", "latency_seconds", "look_number", "image_codes", "item_ids", "item_titles", "styling_note", "recommendation_summary", "input_tokens", "output_tokens"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for look in result.looks:
            selected = [candidate_by_code[code] for code in look.image_codes]
            writer.writerow({
                "run_id": result.run_id, "user_id": result.user_id, "model": result.model, "generated_at": result.generated_at,
                "temperature_f": result.temperature_f, "occasion": result.occasion, "style": result.style,
                "candidate_count": result.candidate_count, "latency_seconds": round(result.latency_seconds, 2), "look_number": look.look_number, "image_codes": " | ".join(look.image_codes),
                "item_ids": " | ".join(candidate.item_id for candidate in selected),
                "item_titles": " | ".join(candidate.title for candidate in selected), "styling_note": look.styling_note,
                "recommendation_summary": result.recommendation_summary, "input_tokens": result.usage.get("input_tokens"),
                "output_tokens": result.usage.get("output_tokens"),
            })

    cards: list[str] = []
    for look in result.looks:
        images = "".join(
            f'<figure><img src="{html.escape(candidate_by_code[code].image_url, quote=True)}" alt="{html.escape(code)}"><figcaption>{html.escape(code)} · {html.escape(candidate_by_code[code].title)}</figcaption></figure>'
            for code in look.image_codes
        )
        cards.append(f"<section><h2>Look {look.look_number}</h2><p>{html.escape(look.styling_note)}</p><div class=\"images\">{images}</div></section>")
    report = f"""<!doctype html><html><head><meta charset=\"utf-8\"><title>Direct Vision Baseline</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;margin:40px;background:#fafafa;color:#171717;max-width:1100px}}.meta,section{{background:white;border:1px solid #e7e7e7;border-radius:16px;padding:20px;margin:18px 0}}.images{{display:flex;gap:16px;flex-wrap:wrap}}figure{{margin:0;width:190px}}img{{width:190px;height:220px;object-fit:cover;border-radius:12px;background:#eee}}figcaption{{margin-top:7px;font-size:14px}}</style>
</head><body><h1>Direct Vision Outfit Baseline</h1><div class=\"meta\"><p><b>Context:</b> {result.temperature_f:g}F · {html.escape(result.occasion)} · {html.escape(result.style)}</p><p><b>Model:</b> {html.escape(result.model)} · <b>Images:</b> {result.candidate_count} · <b>Latency:</b> {result.latency_seconds:.1f}s</p><p>{html.escape(result.recommendation_summary)}</p></div>{''.join(cards)}</body></html>"""
    (output_dir / "report.html").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate direct-vision outfit recommendations against a private closet.")
    parser.add_argument("--user-id", required=True, help="Supabase user UUID whose closet will be evaluated.")
    parser.add_argument("--temperature-f", type=float, required=True)
    parser.add_argument("--occasion", required=True)
    parser.add_argument("--style", default="Any")
    parser.add_argument("--looks", type=int, default=3)
    parser.add_argument("--max-images", type=int, default=40, help="Use 0 for all eligible closet images; 40 is a safer cost/latency default.")
    parser.add_argument("--model", default=settings.openai_vision_model)
    parser.add_argument("--detail", default=settings.openai_vision_detail, choices=["low", "high", "auto"])
    parser.add_argument("--timeout-seconds", type=float, default=max(180, OPENAI_RESPONSES_TIMEOUT_SECONDS * 3))
    parser.add_argument("--output-dir", type=Path, default=evaluation_path("outfits", "baseline_runs"))
    parser.add_argument("--serve", action="store_true", help="Serve the report at localhost after writing artifacts.")
    parser.add_argument("--open", action="store_true", help="Open the local report in the default browser (implies --serve).")
    return parser.parse_args()


def serve_report(output_dir: Path, open_browser: bool) -> None:
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(*args, directory=str(output_dir), **kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    url = "http://127.0.0.1:8765/report.html"
    print(f"Local report: {url}")
    if open_browser:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    args = parse_args()
    if args.looks < 1:
        raise SystemExit("--looks must be at least 1.")
    if args.max_images < 0:
        raise SystemExit("--max-images must be 0 (all) or a positive integer.")

    repository = build_closet_repository()
    evaluator = DirectVisionBaseline()
    candidates = evaluator.candidates_for_items(repository.list_items(args.user_id), args.max_images)
    result, raw_response = evaluator.run(
        user_id=args.user_id, candidates=candidates, temperature_f=args.temperature_f, occasion=args.occasion,
        style=args.style, looks=args.looks, model=args.model, detail=args.detail, timeout_seconds=args.timeout_seconds,
    )
    run_dir = args.output_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{result.run_id[:8]}"
    write_artifacts(run_dir, result, candidates, raw_response)
    print(f"Wrote baseline artifacts to: {run_dir.resolve()}")
    print(f"CSV: {(run_dir / 'results.csv').resolve()}")
    print(f"Report: {(run_dir / 'report.html').resolve()}")
    if args.serve or args.open:
        serve_report(run_dir, open_browser=args.open)


if __name__ == "__main__":
    main()
