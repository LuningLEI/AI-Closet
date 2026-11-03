"""Create a stratified human-review workbook from an outerwear shadow CSV.

This tool is read-only with respect to production data. It embeds local image
previews in a workbook and never sends labels or shadow choices to the app.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import random
import shutil
from typing import Any

import httpx
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from PIL import Image, ImageDraw, ImageOps

from app.models.domain import ClothingItemRecord
from app.repositories.factory import build_closet_repository
from app.services.storage_service import StorageService


SEED = 20261102
YES_NO_UNSURE = "Yes,No,Unsure"
ERROR_REASONS = (
    "Too tight / insufficient room",
    "Too bulky / heavy",
    "Sleeve conflict",
    "Length or proportion conflict",
    "Material conflict",
    "Style mismatch",
    "Weather mismatch",
    "Occasion mismatch",
    "Other",
)


@dataclass(frozen=True)
class SampledGroup:
    sample_id: str
    source_outfit_id: str
    rows: list[dict[str, str]]


def _bool(row: dict[str, str], key: str) -> bool:
    return row.get(key, "").casefold() == "true"


def _choice_family(rows: list[dict[str, str]]) -> str:
    selected = next((row for row in rows if _bool(row, "shadow_selected")), None)
    title = (selected or {}).get("outerwear_title", "Other")
    if title in {"No outerwear", "Cardigan", "Puffer", "Coat"}:
        return title
    if "Jacket" in title or title == "Blazer":
        return "Jacket"
    return "Other"


def _stable_shuffle(values: list[Any], seed: str) -> list[Any]:
    result = list(values)
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    random.Random(int.from_bytes(digest[:8])).shuffle(result)
    return result


def stratified_group_sample(rows: list[dict[str, str]], count: int, seed: int = SEED) -> list[SampledGroup]:
    """Round-robin strata so rare bulk/choice/production cases remain visible."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_outfit_id"]].append(row)
    strata: dict[tuple[str, str, bool], list[tuple[str, list[dict[str, str]]]]] = defaultdict(list)
    for outfit_id, group_rows in grouped.items():
        key = (
            group_rows[0]["inner_bulk"],
            _choice_family(group_rows),
            any(_bool(row, "production_present") for row in group_rows),
        )
        strata[key].append((outfit_id, group_rows))
    queues = {
        key: _stable_shuffle(values, f"{seed}:{key}")
        for key, values in strata.items()
    }
    keys = _stable_shuffle(sorted(queues, key=str), f"{seed}:strata")
    selected: list[tuple[str, list[dict[str, str]]]] = []
    while len(selected) < min(count, len(grouped)):
        progressed = False
        for key in keys:
            if queues[key]:
                selected.append(queues[key].pop())
                progressed = True
                if len(selected) == min(count, len(grouped)):
                    break
        if not progressed:
            break
    return [SampledGroup(f"OW{index:03d}", outfit_id, group_rows) for index, (outfit_id, group_rows) in enumerate(selected, 1)]


def representative_candidates(rows: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    """Keep distinct diagnostic roles instead of merely taking the top-k."""
    eligible = [row for row in rows if not _bool(row, "masked")]
    masked = [row for row in rows if _bool(row, "masked")]
    ordered: list[dict[str, str] | None] = [
        next((row for row in rows if row["outerwear_id"] == "NONE"), None),
        next((row for row in rows if _bool(row, "shadow_selected")), None),
        max(eligible, key=lambda row: float(row["probability"]), default=None),
        max((row for row in rows if _bool(row, "production_present")), key=lambda row: float(row["probability"]), default=None),
        min(masked, key=lambda row: (float(row["fit_score"]), -float(row["total_score"])), default=None),
    ]
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for row in ordered:
        if row is not None and row["outerwear_id"] not in seen:
            seen.add(row["outerwear_id"])
            result.append(row)
    if len(result) < limit:
        remaining = sorted(rows, key=lambda row: (-float(row["probability"]), row["outerwear_id"]))
        for row in remaining:
            if row["outerwear_id"] not in seen:
                result.append(row)
                seen.add(row["outerwear_id"])
                if len(result) == limit:
                    break
    return result[:limit]


def _download_thumbnail(url: str | None, destination: Path, label: str) -> Path:
    try:
        if not url:
            raise ValueError("missing signed image URL")
        response = httpx.get(url, timeout=45, follow_redirects=True)
        response.raise_for_status()
        image = ImageOps.exif_transpose(Image.open(BytesIO(response.content))).convert("RGB")
        image.thumbnail((150, 175))
        canvas = Image.new("RGB", (150, 195), "white")
        canvas.paste(image, ((150 - image.width) // 2, 4))
        ImageDraw.Draw(canvas).text((7, 178), label[:22], fill="black")
    except Exception as error:
        print(f"IMAGE FAILED {label}: {error}")
        canvas = Image.new("RGB", (150, 195), "#E9ECEF")
        ImageDraw.Draw(canvas).text((12, 82), f"Unavailable\n{label[:18]}", fill="#555555")
    canvas.save(destination, "JPEG", quality=80)
    return destination


def _compose_preview(paths: list[Path], destination: Path) -> Path:
    images = [Image.open(path).convert("RGB") for path in paths]
    canvas = Image.new("RGB", (150 * max(1, len(images)), 195), "white")
    for index, image in enumerate(images):
        canvas.paste(image, (index * 150, 0))
    canvas.save(destination, "JPEG", quality=80)
    return destination


def _item_label(item: ClothingItemRecord) -> str:
    return item.subtype or item.category


def _build_thumbnails(items: dict[str, ClothingItemRecord], assets: Path) -> dict[str, Path]:
    storage = StorageService()
    signed = storage.signed_image_urls([item.image_path for item in items.values()], expires_in=3600)
    urls = {
        item.id: signed.get(item.image_path or "") or (item.image_url if item.image_url.startswith("https://") else None)
        for item in items.values()
    }
    paths: dict[str, Path] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(_download_thumbnail, urls[item_id], assets / f"item-{item_id}.jpg", _item_label(item)): item_id
            for item_id, item in items.items()
        }
        for future in as_completed(futures):
            item_id = futures[future]
            paths[item_id] = future.result()
    return paths


def _add_image(sheet, path: Path, cell: str, width: int) -> None:
    image = ExcelImage(str(path))
    image.width = width
    image.height = 176
    sheet.add_image(image, cell)


def _write_instructions(book: Workbook, source_csv: Path, sample_count: int) -> None:
    sheet = book.active
    sheet.title = "Instructions"
    sheet["A1"] = "Outerwear Shadow Human Review"
    sheet["A1"].font = Font(size=17, bold=True)
    lines = [
        "Purpose: identify where optional-outerwear scoring or masking fails; this workbook does not affect production.",
        f"Sample: {sample_count} base outfits, stratified by inner bulk, shadow-choice family, and production-outerwear presence.",
        "Each group includes up to five diagnostic candidates: No outerwear, shadow selection, top probability, production-used, and a high-risk/masked choice.",
        "Physically fits: could this outer layer realistically fit over every pictured upper-body garment? For No outerwear, select N/A.",
        "Looks compatible: judge silhouette/proportion and visual coherence, independently from physical fit.",
        "Preferred choice: select Yes for the best displayed option(s). At least one Yes per sample group is recommended.",
        "Masked candidates remain visible intentionally so mask precision/recall can be measured.",
        f"Source CSV: {source_csv}",
    ]
    for row, line in enumerate(lines, 3):
        sheet.cell(row, 1).value = line
        sheet.cell(row, 1).alignment = Alignment(wrap_text=True, vertical="top")
        sheet.row_dimensions[row].height = 34
    sheet.column_dimensions["A"].width = 125


def _write_review(
    book: Workbook,
    groups: list[SampledGroup],
    items: dict[str, ClothingItemRecord],
    thumbnails: dict[str, Path],
    assets: Path,
) -> int:
    sheet = book.create_sheet("Candidate Review")
    headers = [
        "Sample", "Candidate", "Base outfit", "Candidate preview", "Inner garments", "Outerwear",
        "Inner bulk", "Outer capacity", "Probability", "Rank", "Shadow selected", "Production present",
        "Masked", "Mask reasons", "Total score", "Capability", "Fit", "Sleeve", "Material", "Style",
        "Occasion", "Weather", "Taste", "Physically fits?", "Looks compatible?", "Preferred choice?",
        "Error reason", "Notes", "Source outfit ID", "Outerwear ID",
    ]
    for column, header in enumerate(headers, 1):
        cell = sheet.cell(1, column, header)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "E2"
    sheet.auto_filter.ref = "A1:AD1"
    widths = {"A": 11, "B": 10, "C": 42, "D": 55, "E": 32, "F": 22, "G": 13, "H": 15,
              "I": 13, "J": 9, "K": 15, "L": 16, "M": 11, "N": 30, "O": 13,
              "X": 18, "Y": 20, "Z": 18, "AA": 30, "AB": 40, "AC": 16, "AD": 16}
    for name, width in widths.items():
        sheet.column_dimensions[name].width = width
    for name in ("AC", "AD"):
        sheet.column_dimensions[name].hidden = True

    ynu = DataValidation(type="list", formula1=f'"{YES_NO_UNSURE},N/A"', allow_blank=True)
    yn = DataValidation(type="list", formula1='"Yes,No,Unsure"', allow_blank=True)
    reason = DataValidation(type="list", formula1="=error_reasons", allow_blank=True)
    for validation in (ynu, yn, reason):
        sheet.add_data_validation(validation)

    row_index = 2
    for group in groups:
        base_ids = [value.strip() for value in group.rows[0]["base_item_ids"].split("|") if value.strip()]
        base_paths = [thumbnails[item_id] for item_id in base_ids if item_id in thumbnails]
        base_preview = _compose_preview(base_paths, assets / f"{group.sample_id}-base.jpg")
        candidates = representative_candidates(group.rows)
        for candidate_index, candidate in enumerate(candidates, 1):
            outerwear_id = candidate["outerwear_id"]
            preview_paths = list(base_paths)
            if outerwear_id != "NONE" and outerwear_id in thumbnails:
                preview_paths.append(thumbnails[outerwear_id])
            preview = _compose_preview(preview_paths, assets / f"{group.sample_id}-C{candidate_index}.jpg")
            sheet.row_dimensions[row_index].height = 137
            _add_image(sheet, base_preview, f"C{row_index}", min(300, max(150, 115 * len(base_paths))))
            _add_image(sheet, preview, f"D{row_index}", min(420, max(150, 105 * len(preview_paths))))
            inner_titles = candidate["inner_titles"]
            values = [
                group.sample_id, f"C{candidate_index}", None, None, inner_titles, candidate["outerwear_title"],
                candidate["inner_bulk"], candidate["outer_capacity"], float(candidate["probability"]),
                int(candidate["probability_rank"]), _bool(candidate, "shadow_selected"),
                _bool(candidate, "production_present"), _bool(candidate, "masked"), candidate["mask_reasons"],
                float(candidate["total_score"]), float(candidate["capability_score"]), float(candidate["fit_score"]),
                float(candidate["sleeve_score"]), float(candidate["material_score"]), float(candidate["style_score"]),
                float(candidate["occasion_score"]), float(candidate["weather_score"]), float(candidate["taste_score"]),
                None, None, None, None, None, group.source_outfit_id, outerwear_id,
            ]
            for column, value in enumerate(values, 1):
                if column not in {3, 4}:
                    sheet.cell(row_index, column, value)
                sheet.cell(row_index, column).alignment = Alignment(vertical="top", wrap_text=True)
            ynu.add(sheet.cell(row_index, 24))
            yn.add(sheet.cell(row_index, 25))
            yn.add(sheet.cell(row_index, 26))
            reason.add(sheet.cell(row_index, 27))
            row_index += 1

    last = row_index - 1
    sheet.auto_filter.ref = f"A1:AD{last}"
    sheet.conditional_formatting.add(f"X2:Z{last}", FormulaRule(formula=['X2="Yes"'], fill=PatternFill("solid", fgColor="E2F0D9")))
    sheet.conditional_formatting.add(f"X2:Z{last}", FormulaRule(formula=['X2="No"'], fill=PatternFill("solid", fgColor="FCE4D6")))
    return last - 1


def _write_lists(book: Workbook) -> None:
    sheet = book.create_sheet("Lists")
    for row, value in enumerate(ERROR_REASONS, 1):
        sheet.cell(row, 1, value)
    book.create_named_range("error_reasons", sheet, f"$A$1:$A${len(ERROR_REASONS)}")
    sheet.sheet_state = "hidden"


def _validate_workbook(path: Path, expected_groups: int, expected_rows: int) -> None:
    book = load_workbook(path, read_only=False)
    sheet = book["Candidate Review"]
    groups = {sheet.cell(row, 1).value for row in range(2, sheet.max_row + 1)}
    if len(groups) != expected_groups or sheet.max_row - 1 != expected_rows:
        raise RuntimeError("Workbook verification failed")
    if len(sheet._images) != expected_rows * 2:  # noqa: SLF001 - offline artifact verification
        raise RuntimeError("Workbook image verification failed")


def build_annotation(source_csv: Path, source_manifest: Path, output_dir: Path, sample_count: int) -> tuple[Path, Path, Path]:
    rows = list(csv.DictReader(source_csv.open(encoding="utf-8")))
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    groups = stratified_group_sample(rows, sample_count)
    sampled_rows = [row for group in groups for row in representative_candidates(group.rows)]
    item_ids = {
        item_id.strip()
        for group in groups
        for item_id in group.rows[0]["base_item_ids"].split("|")
        if item_id.strip()
    }
    item_ids.update(row["outerwear_id"] for row in sampled_rows if row["outerwear_id"] != "NONE")

    repository = build_closet_repository()
    all_items = repository.list_items_for_outfit_candidates(manifest["source_user_id"])
    items = {item.id: item for item in all_items if item.id in item_ids}
    missing = item_ids - set(items)
    if missing:
        raise RuntimeError(f"Missing {len(missing)} sampled closet items")

    output_dir.mkdir(parents=True, exist_ok=True)
    assets = output_dir / ".annotation_assets"
    assets.mkdir(exist_ok=True)
    try:
        thumbnails = _build_thumbnails(items, assets)
        book = Workbook()
        _write_instructions(book, source_csv, len(groups))
        _write_lists(book)
        review_rows = _write_review(book, groups, items, thumbnails, assets)
        workbook_path = output_dir / "outerwear_shadow_annotation.xlsx"
        book.save(workbook_path)
        _validate_workbook(workbook_path, len(groups), review_rows)

        sample_csv = output_dir / "outerwear_shadow_annotation_sample.csv"
        with sample_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(sampled_rows[0]))
            writer.writeheader()
            writer.writerows(sampled_rows)
        summary = {
            "source_csv": str(source_csv.resolve()),
            "source_manifest": str(source_manifest.resolve()),
            "production_writes": False,
            "model_calls": 0,
            "seed": SEED,
            "requested_base_outfits": sample_count,
            "sampled_base_outfits": len(groups),
            "candidate_review_rows": review_rows,
            "bulk_distribution": dict(Counter(group.rows[0]["inner_bulk"] for group in groups)),
            "choice_distribution": dict(Counter(_choice_family(group.rows) for group in groups)),
            "groups_with_production_outerwear": sum(any(_bool(row, "production_present") for row in group.rows) for group in groups),
            "embedded_images": review_rows * 2,
        }
        output_manifest = output_dir / "annotation_manifest.json"
        output_manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return workbook_path, sample_csv, output_manifest
    finally:
        shutil.rmtree(assets, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=100)
    args = parser.parse_args()
    paths = build_annotation(args.source_csv, args.source_manifest, args.output_dir, args.sample_count)
    print("\n".join(str(path.resolve()) for path in paths))


if __name__ == "__main__":
    main()
