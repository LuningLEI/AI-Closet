"""Compare picture, vector-only, and current hybrid outfit recommendation methods."""

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import re
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from math import sqrt
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageOps

from tools.evaluation.baseline_eval import BaselineCandidate, DirectVisionBaseline
from tools.evaluation.paths import evaluation_path
from app.core.config import settings
from app.models.domain import ClothingItemRecord, RecommendationContext
from app.repositories.factory import build_closet_repository
from app.services.embedding_service import EmbeddingService, recommendation_context_text
from app.services.recommendation import RecommendationEngine
from app.services.recommendation.candidates import CandidateGenerator
from app.services.recommendation.models import Candidate
from app.services.recommendation.rules import profile_memory_text


@dataclass(frozen=True)
class MethodLook:
    method: str
    look_number: int
    image_codes: list[str]
    score: float | None
    note: str


@dataclass(frozen=True)
class MethodRun:
    method: str
    definition: str
    prompt_or_query: str
    latency_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    looks: list[MethodLook]


def contact_sheet_content(sheet_paths: list[Path], prompt: str) -> list[dict[str, str]]:
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    for path in sheet_paths:
        content.append({"type": "input_image", "image_url": _data_url(path), "detail": "high"})
    return content


def _build_contact_sheets(candidates: list[BaselineCandidate], output_dir: Path, per_sheet: int = 12) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    cell_width, cell_height, columns = 300, 340, 4
    rows = (per_sheet + columns - 1) // columns
    for sheet_index, start in enumerate(range(0, len(candidates), per_sheet), start=1):
        batch = candidates[start : start + per_sheet]
        canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
        draw = ImageDraw.Draw(canvas)
        for index, candidate in enumerate(batch):
            x, y = (index % columns) * cell_width, (index // columns) * cell_height
            try:
                image = ImageOps.exif_transpose(Image.open(BytesIO(_image_bytes(candidate.image_url)))).convert("RGB")
                image.thumbnail((cell_width - 24, cell_height - 62))
                canvas.paste(image, (x + (cell_width - image.width) // 2, y + 10))
            except Exception as error:
                draw.text((x + 12, y + 40), f"Unavailable\n{candidate.code}", fill="black")
                print(f"CONTACT SHEET IMAGE FAILED: {candidate.code}: {error}")
            draw.rectangle((x, y + cell_height - 42, x + cell_width, y + cell_height), fill="black")
            draw.text((x + 12, y + cell_height - 30), candidate.code, fill="white")
        path = output_dir / f"sheet-{sheet_index:02d}.jpg"
        canvas.save(path, quality=88)
        paths.append(path)
    return paths


def _image_bytes(url: str) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    return response.content


def _data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def vector_only_recommendations(
    items: list[ClothingItemRecord],
    context: RecommendationContext,
    preferences: dict[str, Any],
    embedding_service: EmbeddingService,
    limit: int,
) -> tuple[list[tuple[Candidate, float]], str, dict[str, Any] | None]:
    generator = CandidateGenerator()
    recognized_items = generator.filter_recognized_items(items, preferences)
    candidates = generator.generate(recognized_items, context, preferences)
    query = recommendation_context_text(context) + " " + profile_memory_text(preferences, context.occasion)
    query_vector, usage = embedding_service.create_embedding_with_usage(query)
    if not query_vector:
        return [], query, usage

    scored = [(candidate, _cosine(query_vector, _outfit_vector(candidate))) for candidate in candidates]
    scored = [(candidate, score) for candidate, score in scored if score is not None]
    scored.sort(key=lambda pair: (-pair[1], pair[0].identifier))
    selected: list[tuple[Candidate, float]] = []
    seen_leads: set[str] = set()
    for candidate, score in scored:
        lead = candidate.lead_item_id
        if lead and lead in seen_leads:
            continue
        selected.append((candidate, score))
        if lead:
            seen_leads.add(lead)
        if len(selected) == limit:
            break
    return selected, query, usage


def _outfit_vector(candidate: Candidate) -> list[float] | None:
    vectors = [item.semantic_vector for item in candidate.items if item.semantic_vector]
    if not vectors:
        return None
    dimension = len(vectors[0])
    vectors = [vector for vector in vectors if len(vector) == dimension]
    return [sum(vector[index] for vector in vectors) / len(vectors) for index in range(dimension)]


def _cosine(left: list[float], right: list[float] | None) -> float | None:
    if not right or len(left) != len(right):
        return None
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else None


def write_comparison(output_dir: Path, context: RecommendationContext, candidates: list[BaselineCandidate], runs: list[MethodRun]) -> None:
    code_map = {candidate.item_id: candidate.code for candidate in candidates}
    candidate_map = {candidate.code: candidate for candidate in candidates}
    output_dir.mkdir(parents=True, exist_ok=True)
    report_images = _write_report_images(
        output_dir,
        {candidate.code: candidate.image_url for candidate in candidates},
        {code for run in runs for look in run.looks for code in look.image_codes},
    )
    (output_dir / "prompts.json").write_text(json.dumps({run.method: run.prompt_or_query for run in runs}, indent=2), encoding="utf-8")

    fields = ["method", "definition", "prompt_or_query", "latency_seconds", "input_tokens", "cached_input_tokens", "output_tokens", "look_number", "image_codes", "item_ids", "item_titles", "score", "note"]
    with (output_dir / "comparison.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            for look in run.looks:
                selected = [candidate_map[code] for code in look.image_codes if code in candidate_map]
                writer.writerow({
                    "method": run.method, "definition": run.definition, "prompt_or_query": run.prompt_or_query,
                    "latency_seconds": round(run.latency_seconds, 2), "input_tokens": run.input_tokens,
                    "cached_input_tokens": run.cached_input_tokens, "output_tokens": run.output_tokens, "look_number": look.look_number,
                    "image_codes": " | ".join(look.image_codes), "item_ids": " | ".join(item.item_id for item in selected),
                    "item_titles": " | ".join(item.title for item in selected), "score": look.score, "note": look.note,
                })

    sections: list[str] = []
    for run in runs:
        looks_html = []
        for look in run.looks:
            images = "".join(
                f'<figure><img src="{html.escape(report_images.get(code, candidate_map[code].image_url), quote=True)}"><figcaption>{html.escape(code)} · {html.escape(candidate_map[code].title)}</figcaption></figure>'
                for code in look.image_codes if code in candidate_map
            )
            score = f" · score {look.score:.3f}" if look.score is not None else ""
            looks_html.append(f"<article><h3>Look {look.look_number}{score}</h3><p>{html.escape(look.note)}</p><div class=\"images\">{images}</div></article>")
        cached = f" ({run.cached_input_tokens} cached)" if run.cached_input_tokens is not None else ""
        sections.append(f"<section><h2>{html.escape(run.method)}</h2><p>{html.escape(run.definition)}</p><p><b>Latency:</b> {run.latency_seconds:.1f}s · <b>Tokens:</b> {run.input_tokens or 'n/a'} in{cached} / {run.output_tokens or 'n/a'} out</p><details><summary>Prompt / query</summary><pre>{html.escape(run.prompt_or_query)}</pre></details>{''.join(looks_html)}</section>")
    page = f"""<!doctype html><meta charset=\"utf-8\"><title>Recommendation Comparison</title><style>body{{font-family:-apple-system,sans-serif;max-width:1200px;margin:36px;background:#fafafa;color:#111}}section,article{{background:white;border:1px solid #ddd;border-radius:14px;padding:18px;margin:18px 0}}article{{border-color:#eee}}.images{{display:flex;gap:12px;flex-wrap:wrap}}figure{{margin:0;width:170px}}img{{width:170px;height:205px;object-fit:cover;border-radius:10px;background:#eee}}figcaption{{font-size:13px;margin-top:5px}}pre{{white-space:pre-wrap}}summary{{cursor:pointer;color:#06e}}</style><h1>Recommendation Method Comparison</h1><p><b>Context:</b> {context.temperature_f:g}F · {html.escape(context.occasion)} · {html.escape(context.preferred_style or 'Any')}</p>{''.join(sections)}"""
    (output_dir / "comparison.html").write_text(page, encoding="utf-8")


def _write_report_images(output_dir: Path, image_urls_by_code: dict[str, str], codes: set[str]) -> dict[str, str]:
    image_dir = output_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: dict[str, str] = {}
    for code in sorted(codes):
        image_url = image_urls_by_code.get(code)
        if not image_url:
            continue
        path = image_dir / f"{code}.jpg"
        try:
            path.write_bytes(_image_bytes(image_url))
            saved_paths[code] = f"images/{path.name}"
        except Exception as error:
            print(f"REPORT IMAGE FAILED: {code}: {error}")
    return saved_paths


def refresh_report_images(report_dir: Path, candidates: list[BaselineCandidate]) -> int:
    """Restore local report images after the original Supabase signed URLs expire."""
    if not report_dir.is_dir():
        raise ValueError(f"Comparison run directory does not exist: {report_dir}")
    urls_by_item_id = {candidate.item_id: candidate.image_url for candidate in candidates}
    refreshed_scenarios = 0
    image_pattern = re.compile(r'(<figure><img src=")[^"]*("><figcaption>)(I\d+)( ·)')
    for csv_path in sorted(report_dir.glob("*/comparison.csv")):
        image_urls_by_code: dict[str, str] = {}
        with csv_path.open(newline="", encoding="utf-8") as file:
            for row in csv.DictReader(file):
                for code, item_id in zip(row["image_codes"].split(" | "), row["item_ids"].split(" | ")):
                    if item_id in urls_by_item_id:
                        image_urls_by_code[code] = urls_by_item_id[item_id]
        saved_paths = _write_report_images(csv_path.parent, image_urls_by_code, set(image_urls_by_code))
        html_path = csv_path.parent / "comparison.html"
        if html_path.is_file():
            page = html_path.read_text(encoding="utf-8")
            def replace_image_source(match: re.Match[str]) -> str:
                relative_path = saved_paths.get(match.group(3))
                if not relative_path:
                    return match.group(0)
                return f"{match.group(1)}{relative_path}{match.group(2)}{match.group(3)}{match.group(4)}"

            page = image_pattern.sub(
                replace_image_source,
                page,
            )
            html_path.write_text(page, encoding="utf-8")
        refreshed_scenarios += 1
    return refreshed_scenarios


def archive_source_images(candidates: list[BaselineCandidate], output_dir: Path) -> Path:
    archive_path = output_dir / "closet_picture_codes.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for candidate in candidates:
            archive.writestr(f"{candidate.code}.jpg", _image_bytes(candidate.image_url))
    return archive_path


def write_index(output_dir: Path, scenarios: list[tuple[str, RecommendationContext]]) -> None:
    links = "".join(
        f'<li><a href="{html.escape(scenario_id)}/comparison.html">{html.escape(context.temperature_f.__format__("g"))}F · {html.escape(context.occasion)}</a></li>'
        for scenario_id, context in scenarios
    )
    page = f"""<!doctype html><meta charset=\"utf-8\"><title>Recommendation Comparison Scenarios</title><style>body{{font-family:-apple-system,sans-serif;max-width:760px;margin:48px;background:#fafafa;color:#111}}main{{background:white;border:1px solid #ddd;border-radius:16px;padding:28px}}a{{color:#06e}}li{{margin:12px 0}}</style><main><h1>Recommendation Method Comparison</h1><p>Each scenario compares a contact-sheet vision stylist, database semantic-vector ranking, and the current hybrid model.</p><p><a href=\"comparison_all_scenarios.csv\">Download combined CSV</a></p><ul>{links}</ul></main>"""
    (output_dir / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create picture, vector-only, and hybrid recommendation comparison artifacts.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--temperature-f", type=float, action="append", help="Repeat for multiple temperature scenarios.")
    parser.add_argument("--occasion", action="append", help="Repeat to test every temperature/occasion combination.")
    parser.add_argument("--style", default="Any")
    parser.add_argument("--looks", default=3, type=int)
    parser.add_argument("--output-dir", type=Path, default=evaluation_path("outfits", "comparison_runs"))
    parser.add_argument("--archive-source-images", action="store_true", help="Create a local ZIP of code-labelled source images; it is not sent to OpenAI.")
    parser.add_argument("--refresh-images-run", type=Path, help="Restore local images for an existing comparison run without calling OpenAI.")
    args = parser.parse_args()

    repository = build_closet_repository()
    items = repository.list_items_for_recommendation(args.user_id)
    picture_baseline = DirectVisionBaseline()
    candidates = picture_baseline.candidates_for_items(items, max_images=0)
    if args.refresh_images_run:
        refreshed = refresh_report_images(args.refresh_images_run, candidates)
        print(f"Restored local images for {refreshed} scenario report(s): {args.refresh_images_run.resolve()}")
        return
    if not args.temperature_f or not args.occasion:
        parser.error("--temperature-f and --occasion are required unless --refresh-images-run is used.")

    preference_record = repository.get_preferences(args.user_id)
    preferences = preference_record.get("preferences", preference_record)
    output_dir = args.output_dir / time.strftime("%Y%m%d-%H%M%S")
    code_by_item_id = {candidate.item_id: candidate.code for candidate in candidates}
    embedding_service = EmbeddingService()
    sheet_paths = _build_contact_sheets(candidates, output_dir / "contact_sheets")
    combined_rows: list[dict[str, str]] = []
    scenarios: list[tuple[str, RecommendationContext]] = []
    for temperature_f in args.temperature_f:
        for occasion in args.occasion:
            scenario_id = f"{temperature_f:g}F-{occasion.lower().replace(' ', '-') }"
            scenario_dir = output_dir / scenario_id
            context = RecommendationContext(occasion=occasion, temperature_f=temperature_f, preferred_style=None if args.style == "Any" else args.style, limit=args.looks)
            scenarios.append((scenario_id, context))
            picture_prompt = f"""You are a personal wardrobe styling assistant. The supplied contact sheets show the user's closet; every garment is labelled with an I-code. Create exactly {args.looks} distinct outfits for {temperature_f:g}F, occasion {occasion}, style {args.style}. In each outfit selection, use only the supplied I-codes. Do not invent garments or codes. A look may use a dress/jumpsuit, or one top plus one bottom; outerwear and accessories are optional. Choose only garments you can identify clearly."""
            started = time.perf_counter()
            picture_result, _ = picture_baseline.run(user_id=args.user_id, candidates=candidates, temperature_f=temperature_f, occasion=occasion, style=args.style, looks=args.looks, model=settings.openai_vision_model, detail="high", timeout_seconds=240, input_content=contact_sheet_content(sheet_paths, picture_prompt))
            picture_run = MethodRun("baseline-picture", "Personal-stylist vision selection over code-labelled contact sheets; no catalog metadata, vectors, or rules.", picture_prompt, time.perf_counter() - started, picture_result.usage.get("input_tokens"), picture_result.usage.get("output_tokens"), (picture_result.usage.get("input_tokens_details") or {}).get("cached_tokens"), [MethodLook("baseline-picture", look.look_number, look.image_codes, None, look.styling_note) for look in picture_result.looks])

            started = time.perf_counter()
            vector_recommendations, vector_query, vector_usage = vector_only_recommendations(items, context, preferences, embedding_service, args.looks)
            vector_run = MethodRun("baseline-vector", "Structured candidate combinations ranked only by cosine similarity between the context embedding and averaged database semantic vectors.", vector_query, time.perf_counter() - started, (vector_usage or {}).get("prompt_tokens"), None, None, [MethodLook("baseline-vector", index, [code_by_item_id[item.id] for item in candidate.items if item.id in code_by_item_id], score, "Vector-only ranking: no weather, occasion, color, or compatibility score is applied after candidate generation.") for index, (candidate, score) in enumerate(vector_recommendations, start=1)])

            started = time.perf_counter()
            current_recommendations, current_usage = RecommendationEngine().recommend_with_usage(items, context, preferences)
            current_run = MethodRun("current-model", "Current hybrid engine: one context embedding plus structured candidate generation and local semantic, weather, occasion, style, color, completeness, and diversity ranking.", recommendation_context_text(context) + " " + profile_memory_text(preferences, context.occasion), time.perf_counter() - started, (current_usage or {}).get("prompt_tokens"), None, None, [MethodLook("current-model", index, [code_by_item_id[item.id] for item in recommendation.items if item.id in code_by_item_id], recommendation.score, "; ".join(recommendation.reasons + recommendation.styling_notes)) for index, recommendation in enumerate(current_recommendations, start=1)])

            write_comparison(scenario_dir, context, candidates, [picture_run, vector_run, current_run])
            with (scenario_dir / "comparison.csv").open(newline="", encoding="utf-8") as file:
                for row in csv.DictReader(file):
                    combined_rows.append({"scenario": scenario_id, "temperature_f": f"{temperature_f:g}", "occasion": occasion, **row})

    with (output_dir / "comparison_all_scenarios.csv").open("w", newline="", encoding="utf-8") as file:
        fields = ["scenario", "temperature_f", "occasion", "method", "definition", "prompt_or_query", "latency_seconds", "input_tokens", "cached_input_tokens", "output_tokens", "look_number", "image_codes", "item_ids", "item_titles", "score", "note"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(combined_rows)
    write_index(output_dir, scenarios)
    if args.archive_source_images:
        print(f"Image archive: {archive_source_images(candidates, output_dir)}")
    print(f"Scenario reports: {output_dir.resolve()}")
    print(f"Combined comparison CSV: {(output_dir / 'comparison_all_scenarios.csv').resolve()}")


if __name__ == "__main__":
    main()
