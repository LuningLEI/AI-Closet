"""Fill baseline-picture and baseline-vector columns in a human evaluation workbook."""

from __future__ import annotations

import argparse
import base64
import json
import shutil
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from math import sqrt
from pathlib import Path
from typing import Any

import httpx
from openpyxl import load_workbook
from PIL import Image, ImageDraw, ImageOps

from tools.evaluation.baseline_eval import DirectVisionBaseline
from app.core.config import settings
from app.core.constants import OPENAI_RESPONSES_URL
from app.models.domain import ClothingItemRecord, RecommendationContext
from app.repositories.factory import build_closet_repository
from app.services.embedding_service import EmbeddingService, recommendation_context_text
from app.services.recommendation.rules import profile_memory_text
from app.services.taxonomy import OCCASIONS, STYLES


SEASONS = ["Spring/Fall", "Summer", "Winter"]
VERDICTS = ["Inappropriate", "Neutral", "Appropriate"]


def _image_bytes(url: str) -> bytes:
    if url.startswith("data:"):
        return base64.b64decode(url.split(",", 1)[1])
    response = httpx.get(url, timeout=45)
    response.raise_for_status()
    return response.content


def _data_url(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _download_images(codes_to_urls: dict[str, str]) -> dict[str, bytes]:
    image_bytes: dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_image_bytes, url): code for code, url in codes_to_urls.items()}
        for future in as_completed(futures):
            code = futures[future]
            image_bytes[code] = future.result()
    return image_bytes


def _response(content: list[dict[str, str]], schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    response = httpx.post(
        OPENAI_RESPONSES_URL,
        headers={"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"},
        json={
            "model": settings.openai_vision_model,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": "workbook_baseline_labels", "schema": schema, "strict": True}},
        },
        timeout=240,
    )
    response.raise_for_status()
    payload = response.json()
    output_text = payload.get("output_text") or ""
    if not output_text:
        output_text = "\n".join(
            block.get("text", "")
            for output in payload.get("output", [])
            for block in output.get("content", [])
            if block.get("type") in {"output_text", "text"}
        )
    return json.loads(output_text), payload.get("usage") or {}


def _contact_sheets(image_bytes_by_code: dict[str, bytes], directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    codes = sorted(image_bytes_by_code)
    for page, start in enumerate(range(0, len(codes), 12), start=1):
        batch = codes[start : start + 12]
        canvas = Image.new("RGB", (960, 960), "white")
        draw = ImageDraw.Draw(canvas)
        for index, code in enumerate(batch):
            x, y = (index % 4) * 240, (index // 4) * 320
            image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes_by_code[code]))).convert("RGB")
            image.thumbnail((220, 268))
            canvas.paste(image, (x + (240 - image.width) // 2, y + 8))
            draw.rectangle((x, y + 286, x + 240, y + 320), fill="black")
            draw.text((x + 10, y + 296), code, fill="white")
        path = directory / f"items-{page:02d}.jpg"
        canvas.save(path, quality=84)
        paths.append(path)
    return paths


def _item_picture_labels(image_bytes_by_code: dict[str, bytes], directory: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    sheets = _contact_sheets(image_bytes_by_code, directory)
    codes = sorted(image_bytes_by_code)
    prompt = """You are labeling a personal closet from code-labelled contact sheets. For every I-code, choose one occasion, one style, and one season group. Use only the provided labels. Return labels for every supplied code. Do not use catalog metadata or invent codes."""
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_image", "image_url": _data_url(path), "detail": "high"} for path in sheets)
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"items": {"type": "array", "minItems": len(codes), "maxItems": len(codes), "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"code": {"type": "string", "enum": codes}, "occasion": {"type": "string", "enum": OCCASIONS}, "style": {"type": "string", "enum": STYLES}, "season": {"type": "string", "enum": SEASONS}},
            "required": ["code", "occasion", "style", "season"],
        }}}, "required": ["items"],
    }
    payload, usage = _response(content, schema)
    labels = {item["code"]: item for item in payload["items"]}
    if set(labels) != set(codes):
        raise ValueError("baseline-picture did not return exactly one label set per garment.")
    return labels, usage


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def _average(vectors: list[list[float]]) -> list[float] | None:
    if not vectors:
        return None
    size = len(vectors[0])
    usable = [vector for vector in vectors if len(vector) == size]
    return [sum(vector[index] for vector in usable) / len(usable) for index in range(size)] if usable else None


def _vector_item_labels(items_by_code: dict[str, ClothingItemRecord]) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    service = EmbeddingService()
    options = [("occasion", label, f"a garment appropriate for {label}") for label in OCCASIONS]
    options += [("style", label, f"a {label} fashion garment") for label in STYLES]
    options += [("season", label, f"a garment suitable for {label} weather") for label in SEASONS]
    prototypes: dict[str, list[tuple[str, list[float]]]] = defaultdict(list)
    usage: dict[str, Any] = {"prompt_tokens": 0}
    for dimension, label, text in options:
        vector, response_usage = service.create_embedding_with_usage(text)
        if vector:
            prototypes[dimension].append((label, vector))
        usage["prompt_tokens"] += (response_usage or {}).get("prompt_tokens", 0)
    labels: dict[str, dict[str, str]] = {}
    for code, item in items_by_code.items():
        labels[code] = {
            dimension: max(options, key=lambda option: _cosine(item.semantic_vector, option[1]))[0] if item.semantic_vector and options else ""
            for dimension, options in prototypes.items()
        }
    return labels, usage


def _outfit_preview(codes: list[str], image_bytes_by_code: dict[str, bytes], path: Path) -> Path:
    canvas = Image.new("RGB", (150 * len(codes), 180), "white")
    draw = ImageDraw.Draw(canvas)
    for index, code in enumerate(codes):
        image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes_by_code[code]))).convert("RGB")
        image.thumbnail((138, 145))
        x = index * 150 + (150 - image.width) // 2
        canvas.paste(image, (x, 4))
        draw.text((index * 150 + 8, 157), code, fill="black")
    canvas.save(path, quality=82)
    return path


def _outfit_picture_labels(outfits: list[dict[str, Any]], image_bytes_by_code: dict[str, bytes], directory: Path) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    directory.mkdir(parents=True, exist_ok=True)
    answers: dict[str, dict[str, str]] = {}
    usages: list[dict[str, Any]] = []
    for batch_number, start in enumerate(range(0, len(outfits), 10), start=1):
        batch = outfits[start : start + 10]
        previews = [_outfit_preview(row["codes"], image_bytes_by_code, directory / f"{row['id']}.jpg") for row in batch]
        canvas = Image.new("RGB", (700, 900), "white")
        draw = ImageDraw.Draw(canvas)
        for index, (row, preview) in enumerate(zip(batch, previews)):
            image = Image.open(preview).convert("RGB")
            image.thumbnail((330, 145))
            x, y = (index % 2) * 350, (index // 2) * 180
            canvas.paste(image, (x + (350 - image.width) // 2, y + 20))
            draw.text((x + 8, y + 2), row["id"], fill="black")
        sheet_path = directory / f"outfits-{batch_number:02d}.jpg"
        canvas.save(sheet_path, quality=84)
        prompt_lines = ["Judge each labelled outfit for its own scenario."]
        prompt_lines += [f"{row['id']}: {row['prompt']}" for row in batch]
        prompt_lines.append("Wearable means appropriate for temperature and occasion. Aesthetic means the garment combination looks coordinated. Use only the three provided verdicts.")
        codes = [row["id"] for row in batch]
        schema = {"type": "object", "additionalProperties": False, "properties": {"outfits": {"type": "array", "minItems": len(codes), "maxItems": len(codes), "items": {"type": "object", "additionalProperties": False, "properties": {"id": {"type": "string", "enum": codes}, "wearable": {"type": "string", "enum": VERDICTS}, "aesthetic": {"type": "string", "enum": VERDICTS}}, "required": ["id", "wearable", "aesthetic"]}}}, "required": ["outfits"]}
        payload, usage = _response([{"type": "input_text", "text": "\n".join(prompt_lines)}, {"type": "input_image", "image_url": _data_url(sheet_path), "detail": "high"}], schema)
        answers.update({row["id"]: row for row in payload["outfits"]})
        usages.append(usage)
    return answers, usages


def _thirds(scores: dict[str, float]) -> dict[str, str]:
    ordered = sorted(scores.items(), key=lambda pair: pair[1])
    lower, upper = len(ordered) / 3, len(ordered) * 2 / 3
    return {identifier: "Inappropriate" if index < lower else "Neutral" if index < upper else "Appropriate" for index, (identifier, _) in enumerate(ordered)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill baseline columns in a human evaluation workbook.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--workbook", type=Path, required=True)
    args = parser.parse_args()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for baseline-picture.")

    repository = build_closet_repository()
    items = repository.list_items_for_recommendation(args.user_id)
    preference_record = repository.get_preferences(args.user_id)
    preferences = preference_record.get("preferences", preference_record)
    candidates = DirectVisionBaseline().candidates_for_items(items, max_images=0)
    urls_by_item_id = {candidate.item_id: candidate.image_url for candidate in candidates}

    workbook = load_workbook(args.workbook)
    garment_sheet = workbook["Garment Labels"]
    outfit_sheet = workbook["Outfit Judgments"]
    items_by_code: dict[str, ClothingItemRecord] = {}
    urls_by_code: dict[str, str] = {}
    item_by_id = {item.id: item for item in items}
    for row in range(3, garment_sheet.max_row + 1):
        code, item_id = garment_sheet.cell(row, 2).value, garment_sheet.cell(row, 3).value
        if code and item_id in item_by_id and item_id in urls_by_item_id:
            items_by_code[code] = item_by_id[item_id]
            urls_by_code[code] = urls_by_item_id[item_id]
    work_dir = args.workbook.parent / ".baseline_fill_assets"
    try:
        image_bytes_by_code = _download_images(urls_by_code)
        picture_item_labels, picture_item_usage = _item_picture_labels(image_bytes_by_code, work_dir / "garments")
        vector_item_labels, vector_item_usage = _vector_item_labels(items_by_code)
        for row in range(3, garment_sheet.max_row + 1):
            code = garment_sheet.cell(row, 2).value
            if code not in items_by_code:
                continue
            garment_sheet.cell(row, 7).value = picture_item_labels[code]["occasion"]
            garment_sheet.cell(row, 8).value = vector_item_labels[code]["occasion"]
            garment_sheet.cell(row, 12).value = picture_item_labels[code]["style"]
            garment_sheet.cell(row, 13).value = vector_item_labels[code]["style"]
            garment_sheet.cell(row, 17).value = picture_item_labels[code]["season"]
            garment_sheet.cell(row, 18).value = vector_item_labels[code]["season"]

        outfits: list[dict[str, Any]] = []
        for row in range(3, outfit_sheet.max_row + 1):
            codes = str(outfit_sheet.cell(row, 3).value).split(" | ")
            outfits.append({"row": row, "id": outfit_sheet.cell(row, 2).value, "codes": codes, "prompt": outfit_sheet.cell(row, 4).value, "temperature": outfit_sheet.cell(row, 5).value, "occasion": outfit_sheet.cell(row, 7).value, "style": outfit_sheet.cell(row, 8).value})
        picture_outfit_labels, picture_outfit_usage = _outfit_picture_labels(outfits, image_bytes_by_code, work_dir / "outfits")
        semantic_scores: dict[str, float] = {}
        coherence_scores: dict[str, float] = {}
        for outfit in outfits:
            context = RecommendationContext(occasion=outfit["occasion"], temperature_f=float(outfit["temperature"]), preferred_style=outfit["style"])
            query, _ = EmbeddingService().create_embedding_with_usage(recommendation_context_text(context) + " " + profile_memory_text(preferences, context.occasion))
            vectors = [items_by_code[code].semantic_vector for code in outfit["codes"] if items_by_code[code].semantic_vector]
            outfit_vector = _average(vectors)
            semantic_scores[outfit["id"]] = _cosine(query, outfit_vector)
            pairs = [_cosine(vectors[left], vectors[right]) for left in range(len(vectors)) for right in range(left + 1, len(vectors))]
            coherence_scores[outfit["id"]] = sum(pairs) / len(pairs) if pairs else 0.0
        vector_wearable, vector_aesthetic = _thirds(semantic_scores), _thirds(coherence_scores)
        for outfit in outfits:
            row, identifier = outfit["row"], outfit["id"]
            outfit_sheet.cell(row, 12).value = picture_outfit_labels[identifier]["wearable"]
            outfit_sheet.cell(row, 13).value = vector_wearable[identifier]
            outfit_sheet.cell(row, 17).value = picture_outfit_labels[identifier]["aesthetic"]
            outfit_sheet.cell(row, 18).value = vector_aesthetic[identifier]

        output = args.workbook.with_name(args.workbook.stem + "_with_baselines.xlsx")
        workbook.save(output)
        output.with_suffix(".json").write_text(json.dumps({"picture_item_usage": picture_item_usage, "vector_item_usage": vector_item_usage, "picture_outfit_usage": picture_outfit_usage}, indent=2), encoding="utf-8")
        print(f"Workbook: {output.resolve()}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
