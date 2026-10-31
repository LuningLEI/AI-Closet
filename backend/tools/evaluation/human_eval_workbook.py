"""Create a blinded human/model labeling workbook for closet and outfit evaluation."""

from __future__ import annotations

import argparse
import random
import shutil
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from openpyxl import Workbook
from openpyxl.drawing.image import Image as SpreadsheetImage
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from PIL import Image, ImageDraw, ImageOps

from tools.evaluation.baseline_eval import DirectVisionBaseline
from tools.evaluation.paths import evaluation_path
from app.models.domain import ClothingItemRecord, RecommendationContext
from app.repositories.factory import build_closet_repository
from app.services.recommendation.candidates import CandidateGenerator
from app.services.recommendation.models import Candidate
from app.services.recommendation.rules import recommendation_slot
from app.services.taxonomy import OCCASIONS, STYLES


ANNOTATORS = ["Human 1", "Human 2", "Human 3", "baseline-picture", "baseline-vector"]
SEASON_LABELS = ["Spring/Fall", "Summer", "Winter"]
OUTFIT_VERDICTS = ["Inappropriate", "Neutral", "Appropriate"]
TEMPERATURE_SCENARIOS = [(35, "Cold (<45F)"), (50, "Cool (45-64F)"), (65, "Mild (65-77F)"), (72, "Mild (65-77F)"), (82, "Warm (78F+)"), (90, "Warm (78F+)")]


@dataclass(frozen=True)
class OutfitEvaluationRow:
    outfit_id: str
    item_codes: list[str]
    prompt: str
    temperature_f: int
    temperature_range: str
    occasion: str
    style: str
    candidate: Candidate


def _image_bytes(url: str) -> bytes:
    if url.startswith("data:"):
        return BytesIO(url.split(",", 1)[1].encode("ascii")).getvalue()
    response = httpx.get(url, timeout=45)
    response.raise_for_status()
    return response.content


def _load_image(url: str) -> Image.Image:
    if url.startswith("data:"):
        import base64

        image_bytes = base64.b64decode(url.split(",", 1)[1])
    else:
        image_bytes = _image_bytes(url)
    return ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGB")


def _thumbnail(url: str, destination: Path, size: tuple[int, int] = (130, 150)) -> Path:
    image = _load_image(url)
    image.thumbnail(size)
    canvas = Image.new("RGB", size, "white")
    canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    canvas.save(destination, "JPEG", quality=82)
    return destination


def _placeholder_thumbnail(destination: Path, label: str, size: tuple[int, int] = (130, 150)) -> Path:
    canvas = Image.new("RGB", size, "E9ECEF")
    draw = ImageDraw.Draw(canvas)
    draw.text((12, size[1] // 2 - 8), f"Unavailable\n{label}", fill="555555")
    canvas.save(destination, "JPEG", quality=82)
    return destination


def _build_thumbnails(
    items: list[ClothingItemRecord],
    image_urls: dict[str, str],
    code_by_item_id: dict[str, str],
    assets_dir: Path,
) -> dict[str, Path]:
    """Download in parallel so workbook creation does not stall on one signed URL."""
    thumbnails: dict[str, Path] = {}

    def create(item: ClothingItemRecord) -> tuple[str, Path]:
        code = code_by_item_id[item.id]
        destination = assets_dir / f"{code}.jpg"
        try:
            return item.id, _thumbnail(image_urls[item.id], destination)
        except Exception as error:
            print(f"WORKBOOK IMAGE FAILED: {code}: {error}")
            return item.id, _placeholder_thumbnail(destination, code)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(create, item) for item in items]
        for future in as_completed(futures):
            item_id, path = future.result()
            thumbnails[item_id] = path
    return thumbnails


def _outfit_preview(images: list[tuple[str, Path]], destination: Path) -> Path:
    cell_width, cell_height = 120, 155
    canvas = Image.new("RGB", (max(1, len(images)) * cell_width, cell_height), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (code, path) in enumerate(images):
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell_width - 12, cell_height - 35))
        x = index * cell_width + (cell_width - image.width) // 2
        canvas.paste(image, (x, 4))
        draw.text((index * cell_width + 8, cell_height - 22), code, fill="black")
    canvas.save(destination, "JPEG", quality=84)
    return destination


def _add_image(sheet, path: Path, cell: str, width: int, height: int) -> None:
    image = SpreadsheetImage(str(path))
    image.width = width
    image.height = height
    sheet.add_image(image, cell)


def _add_headers(sheet, groups: list[tuple[str, list[str]]]) -> None:
    sheet["A1"] = "Garment image"
    sheet["B1"] = "I-code"
    sheet["C1"] = "Item ID"
    sheet.merge_cells("A1:A2")
    sheet.merge_cells("B1:B2")
    sheet.merge_cells("C1:C2")
    column = 4
    for group_name, columns in groups:
        start = column
        end = column + len(columns) - 1
        sheet.merge_cells(start_row=1, start_column=start, end_row=1, end_column=end)
        sheet.cell(1, start).value = group_name
        for index, name in enumerate(columns, start=start):
            sheet.cell(2, index).value = name
        column = end + 1

    for row in sheet.iter_rows(min_row=1, max_row=2):
        for cell in row:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.fill = PatternFill("solid", fgColor="1F4E78" if cell.row == 1 else "5B9BD5")
    sheet.row_dimensions[1].height = 28
    sheet.row_dimensions[2].height = 36
    sheet.freeze_panes = "D3"
    sheet.column_dimensions["A"].width = 22
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].hidden = True
    for index in range(4, column):
        sheet.column_dimensions[chr(64 + index)].width = 18


def _write_item_sheet(workbook: Workbook, items: list[ClothingItemRecord], thumbnail_paths: dict[str, Path]) -> None:
    sheet = workbook.create_sheet("Garment Labels")
    _add_headers(
        sheet,
        [
            ("Occasion labels", ANNOTATORS),
            ("Style labels", ANNOTATORS),
            ("Season labels", ANNOTATORS),
        ],
    )

    occasion_validation = DataValidation(type="list", formula1='"' + ",".join(OCCASIONS) + '"', allow_blank=True)
    style_validation = DataValidation(type="list", formula1='"' + ",".join(STYLES) + '"', allow_blank=True)
    season_validation = DataValidation(type="list", formula1="=season_labels", allow_blank=True)
    sheet.add_data_validation(occasion_validation)
    sheet.add_data_validation(style_validation)
    sheet.add_data_validation(season_validation)

    for index, item in enumerate(items, start=1):
        row = index + 2
        code = f"I{index:03d}"
        sheet.cell(row, 2).value = code
        sheet.cell(row, 3).value = item.id
        sheet.row_dimensions[row].height = 116
        _add_image(sheet, thumbnail_paths[item.id], f"A{row}", 112, 112)
        occasion_validation.add(f"D{row}:H{row}")
        style_validation.add(f"I{row}:M{row}")
        season_validation.add(f"N{row}:R{row}")


def _build_outfit_rows(
    items: list[ClothingItemRecord],
    code_by_item_id: dict[str, str],
    preferences: dict,
    requested_count: int,
) -> list[OutfitEvaluationRow]:
    generator = CandidateGenerator()
    recognized_items = generator.filter_recognized_items(items, preferences)
    rng = random.Random(20260923)
    contexts = [
        RecommendationContext(occasion=occasion, temperature_f=temperature, preferred_style=style, limit=3)
        for temperature, temperature_range in TEMPERATURE_SCENARIOS
        for occasion in OCCASIONS
        for style in STYLES
    ]
    rng.shuffle(contexts)
    rows: list[OutfitEvaluationRow] = []
    seen_signatures: set[str] = set()
    grouped: dict[str, list[ClothingItemRecord]] = {}
    for item in recognized_items:
        grouped.setdefault(recommendation_slot(item.category), []).append(item)
    supported_slots = {"FullBody", "Tops", "Bottoms", "Shoes", "Outerwear", "Accessories"}
    available_items = [item for slot, slot_items in grouped.items() if slot in supported_slots for item in slot_items]
    usage: Counter[str] = Counter()

    def choose(slot: str, excluded: set[str] | None = None) -> ClothingItemRecord | None:
        options = [item for item in grouped.get(slot, []) if item.id not in (excluded or set())]
        if not options:
            return None
        minimum = min(usage[item.id] for item in options)
        return rng.choice([item for item in options if usage[item.id] == minimum])

    def has_unused(slot: str) -> bool:
        return any(usage[item.id] == 0 for item in grouped.get(slot, []))

    for attempt in range(requested_count * 30):
        if len(rows) == requested_count:
            return rows
        context = contexts[attempt % len(contexts)]
        anchor = choose_from = min(usage[item.id] for item in available_items)
        anchor = rng.choice([item for item in available_items if usage[item.id] == choose_from])
        anchor_slot = recommendation_slot(anchor.category)
        selected_ids = {anchor.id}
        full_body = anchor if anchor_slot == "FullBody" else None
        top = anchor if anchor_slot == "Tops" else None
        bottom = anchor if anchor_slot == "Bottoms" else None
        shoes = anchor if anchor_slot == "Shoes" else None
        outerwear = anchor if anchor_slot == "Outerwear" else None
        accessory = anchor if anchor_slot == "Accessories" else None

        if full_body is None and top is None and bottom is None:
            if grouped.get("FullBody") and (not grouped.get("Tops") or not grouped.get("Bottoms") or rng.random() < 0.45):
                full_body = choose("FullBody", selected_ids)
            else:
                top = choose("Tops", selected_ids)
                if top:
                    selected_ids.add(top.id)
                bottom = choose("Bottoms", selected_ids)

        if full_body is None:
            if top is None:
                top = choose("Tops", selected_ids)
                if top:
                    selected_ids.add(top.id)
            if bottom is None:
                bottom = choose("Bottoms", selected_ids)

        if not full_body and not (top and bottom):
            continue
        selected_ids.update(item.id for item in [full_body, top, bottom, shoes, outerwear, accessory] if item)

        if shoes is None and grouped.get("Shoes") and (has_unused("Shoes") or rng.random() < 0.55):
            shoes = choose("Shoes", selected_ids)
            if shoes:
                selected_ids.add(shoes.id)
        if outerwear is None and grouped.get("Outerwear") and (has_unused("Outerwear") or rng.random() < 0.35):
            outerwear = choose("Outerwear", selected_ids)
            if outerwear:
                selected_ids.add(outerwear.id)
        if accessory is None and grouped.get("Accessories") and (has_unused("Accessories") or rng.random() < 0.08):
            accessory = choose("Accessories", selected_ids)

        candidate = Candidate(full_body=full_body, top=top, bottom=bottom, shoes=shoes, outerwear=outerwear, accessory=accessory)
        if candidate.identifier in seen_signatures:
            continue
        item_codes = [code_by_item_id[item.id] for item in candidate.items if item.id in code_by_item_id]
        if not item_codes:
            continue
        temperature_range = next(label for temperature, label in TEMPERATURE_SCENARIOS if temperature == context.temperature_f)
        rows.append(
            OutfitEvaluationRow(
                outfit_id=f"O{len(rows) + 1:03d}",
                item_codes=item_codes,
                prompt=(
                    f"Assess this outfit for {context.occasion} at {context.temperature_f:g}F "
                    f"with a {context.preferred_style} style target."
                ),
                temperature_f=int(context.temperature_f),
                temperature_range=temperature_range,
                occasion=context.occasion,
                style=context.preferred_style or "Any",
                candidate=candidate,
            )
        )
        seen_signatures.add(candidate.identifier)
        usage.update(item.id for item in candidate.items)
    raise RuntimeError(f"Only generated {len(rows)} unique structured outfits; expected {requested_count}.")


def _write_outfit_sheet(
    workbook: Workbook,
    rows: list[OutfitEvaluationRow],
    code_by_item_id: dict[str, str],
    thumbnail_paths: dict[str, Path],
    assets_dir: Path,
) -> None:
    sheet = workbook.create_sheet("Outfit Judgments")
    context_headers = ["Outfit preview", "Outfit ID", "Item I-codes", "Prompt", "Temperature", "Temperature range", "Occasion", "Style"]
    for column, header in enumerate(context_headers, start=1):
        cell = sheet.cell(1, column)
        cell.value = header
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.merge_cells(start_row=1, start_column=column, end_row=2, end_column=column)

    for start_column, group_name in [(9, "Wearable: temperature + occasion"), (14, "Aesthetic")]:
        sheet.merge_cells(start_row=1, start_column=start_column, end_row=1, end_column=start_column + len(ANNOTATORS) - 1)
        group_cell = sheet.cell(1, start_column)
        group_cell.value = group_name
        group_cell.font = Font(bold=True, color="FFFFFF")
        group_cell.fill = PatternFill("solid", fgColor="1F4E78")
        group_cell.alignment = Alignment(horizontal="center", vertical="center")
        for offset, annotator in enumerate(ANNOTATORS):
            cell = sheet.cell(2, start_column + offset)
            cell.value = annotator
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="5B9BD5")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    sheet.freeze_panes = None
    sheet.row_dimensions[1].height = 34
    sheet.row_dimensions[2].height = 34
    widths = [50, 12, 28, 52, 14, 19, 16, 16, 18, 18, 18, 20, 20, 18, 18, 18, 20, 20]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width

    verdict_validation = DataValidation(type="list", formula1='"' + ",".join(OUTFIT_VERDICTS) + '"', allow_blank=True)
    sheet.add_data_validation(verdict_validation)
    green_fill = PatternFill("solid", fgColor="E2F0D9")
    yellow_fill = PatternFill("solid", fgColor="FFF2CC")
    red_fill = PatternFill("solid", fgColor="FCE4D6")

    thumbnails_by_code = {code_by_item_id[item_id]: path for item_id, path in thumbnail_paths.items()}

    for index, row_data in enumerate(rows, start=3):
        sheet.row_dimensions[index].height = 126
        preview_path = _outfit_preview(
            [(code, thumbnails_by_code[code]) for code in row_data.item_codes],
            assets_dir / f"{row_data.outfit_id}.jpg",
        )
        _add_image(sheet, preview_path, f"A{index}", 320, 118)
        values = [row_data.outfit_id, " | ".join(row_data.item_codes), row_data.prompt, row_data.temperature_f, row_data.temperature_range, row_data.occasion, row_data.style]
        for column, value in enumerate(values, start=2):
            sheet.cell(index, column).value = value
            sheet.cell(index, column).alignment = Alignment(vertical="center", wrap_text=True)
        verdict_validation.add(f"I{index}:R{index}")

    range_string = f"I3:R{len(rows) + 2}"
    sheet.conditional_formatting.add(range_string, FormulaRule(formula=['I3="Appropriate"'], fill=green_fill))
    sheet.conditional_formatting.add(range_string, FormulaRule(formula=['I3="Neutral"'], fill=yellow_fill))
    sheet.conditional_formatting.add(range_string, FormulaRule(formula=['I3="Inappropriate"'], fill=red_fill))


def _write_instructions_sheet(workbook: Workbook) -> None:
    sheet = workbook.create_sheet("Instructions", 0)
    sheet["A1"] = "Human + Model Evaluation Workbook"
    sheet["A1"].font = Font(bold=True, size=16)
    instructions = [
        "Garment Labels: label each garment independently. Do not consult auto-recognition metadata.",
        "Occasion and Style cells use the existing taxonomy dropdowns. Temperature cells use broad temperature-range tags.",
        "Outfit Judgments: use Appropriate, Neutral, or Inappropriate for the prompt and pictured outfit.",
        "Human 1-3 should be completed independently. Keep baseline-picture and baseline-vector blank until model outputs are generated.",
        "All garment and outfit samples are blind to the current hybrid model score.",
    ]
    for index, instruction in enumerate(instructions, start=3):
        sheet.cell(index, 1).value = instruction
        sheet.cell(index, 1).alignment = Alignment(wrap_text=True, vertical="top")
        sheet.row_dimensions[index].height = 34
    sheet.column_dimensions["A"].width = 120


def _add_validation_lists(workbook: Workbook) -> None:
    sheet = workbook.create_sheet("Lists")
    for row, value in enumerate(SEASON_LABELS, start=1):
        sheet.cell(row, 1).value = value
    workbook.create_named_range("season_labels", sheet, f"$A$1:$A${len(SEASON_LABELS)}")
    sheet.sheet_state = "hidden"


def build_workbook(user_id: str, output_dir: Path, outfit_count: int) -> Path:
    repository = build_closet_repository()
    items = repository.list_items_for_recommendation(user_id)
    preference_record = repository.get_preferences(user_id)
    preferences = preference_record.get("preferences", preference_record)
    candidates = DirectVisionBaseline().candidates_for_items(items, max_images=0)
    image_urls = {candidate.item_id: candidate.image_url for candidate in candidates}
    labeled_items = [item for item in items if item.id in image_urls]
    if not labeled_items:
        raise RuntimeError("No eligible closet images were found for this user.")

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / ".workbook_assets"
    assets_dir.mkdir(exist_ok=True)
    try:
        code_by_item_id = {item.id: f"I{index:03d}" for index, item in enumerate(labeled_items, start=1)}
        thumbnail_paths = _build_thumbnails(labeled_items, image_urls, code_by_item_id, assets_dir)
        workbook = Workbook()
        workbook.remove(workbook.active)
        _add_validation_lists(workbook)
        _write_item_sheet(workbook, labeled_items, thumbnail_paths)
        outfit_rows = _build_outfit_rows(labeled_items, code_by_item_id, preferences, outfit_count)
        _write_outfit_sheet(workbook, outfit_rows, code_by_item_id, thumbnail_paths, assets_dir)
        output_path = output_dir / "closet_outfit_annotation.xlsx"
        workbook.save(output_path)
        return output_path
    finally:
        shutil.rmtree(assets_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a blinded closet and outfit annotation workbook.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--outfit-count", type=int, default=100)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=evaluation_path("outfits", "drafts", time.strftime("%Y%m%d-%H%M%S")),
    )
    args = parser.parse_args()
    output_path = build_workbook(args.user_id, args.output_dir, args.outfit_count)
    print(f"Workbook: {output_path.resolve()}")


if __name__ == "__main__":
    main()
