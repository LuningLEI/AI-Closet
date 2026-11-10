"""Export a paired recognition shadow run comparison to a readable Excel workbook."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageOps


BLUE = "1F4E78"
LIGHT_BLUE = "D9EAF7"
GREEN = "E2F0D9"
RED = "FCE4D6"
GRAY = "E7E6E6"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def prediction(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("normalized_prediction") or result.get("raw_prediction") or result.get(
        "syntax_prediction"
    ) or {}


def field(summary: dict[str, Any], name: str) -> float | None:
    return summary["syntax_prediction_agreement"]["fields"][name]["accuracy"]


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0%}"


def money(value: float | None) -> str:
    return "—" if value is None else f"${value:.6f}"


def add_title(sheet: Any, title: str, width: int) -> None:
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
    cell = sheet.cell(1, 1, title)
    cell.font = Font(color="FFFFFF", bold=True, size=16)
    cell.fill = PatternFill("solid", fgColor=BLUE)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 26


def style_header(sheet: Any, row: int, width: int) -> None:
    for column in range(1, width + 1):
        cell = sheet.cell(row, column)
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor=BLUE)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def export(
    *, baseline_run: Path, candidate_run: Path, previews: Path, output: Path,
) -> None:
    references = read_json(candidate_run / "references.json")
    baseline_summary = read_json(baseline_run / "summary.json")
    candidate_summary = read_json(candidate_run / "summary.json")
    baseline_results = {
        path.stem: read_json(path) for path in (baseline_run / "results").glob("*.json")
    }
    candidate_results = {
        path.stem: read_json(path) for path in (candidate_run / "results").glob("*.json")
    }

    workbook = Workbook()
    summary = workbook.active
    summary.title = "Summary"
    add_title(summary, "Recognition Model Comparison — 10-Item Paired Pilot", 3)
    summary.append(["Scope", "GPT-4.1-mini baseline", "Qwen3-VL-4B current"])
    style_header(summary, 2, 3)
    summary.append(["Evaluation type", "Observed", "Observed"])
    summary.append(["Garments", len(references), len(references)])
    summary.append([
        "Provider call success",
        f"{baseline_summary['items']['model_call_succeeded']}/{len(references)}",
        f"{candidate_summary['items']['model_call_succeeded']}/{len(references)}",
    ])
    summary.append([
        "Valid JSON",
        f"{baseline_summary['items']['json_syntax_valid']}/{len(references)}",
        f"{candidate_summary['items']['json_syntax_valid']}/{len(references)}",
    ])
    summary.append([
        "Accepted by production parser",
        f"{baseline_summary['items']['production_schema_valid']}/{len(references)}",
        f"{candidate_summary['items']['production_schema_valid']}/{len(references)}",
    ])
    summary.append(["Category agreement with stored labels", percent(field(baseline_summary, "category")), percent(field(candidate_summary, "category"))])
    summary.append(["Subtype agreement with stored labels", percent(field(baseline_summary, "subtype")), percent(field(candidate_summary, "subtype"))])
    summary.append(["Mean latency per item", f"{baseline_summary['performance']['latency_seconds']['mean']:.2f} s", f"{candidate_summary['performance']['latency_seconds']['mean']:.2f} s"])
    summary.append(["Measured cost for 10 items", money(baseline_summary["performance"]["estimated_cost_usd"]), money(candidate_summary["performance"]["estimated_cost_usd"])])
    summary.append([])
    summary.append(["Important note", "Stored-label agreement is not the same as human-verified accuracy.", "No extrapolation to 100 items is included."])
    for row in summary.iter_rows(min_row=3, max_row=summary.max_row):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for column, width in enumerate((38, 28, 34), 1):
        summary.column_dimensions[get_column_letter(column)].width = width
    summary.freeze_panes = "A3"

    details = workbook.create_sheet("Item-level Results")
    headers = [
        "#", "Image", "Item ID", "Stored category", "Stored subtype",
        "GPT category", "GPT subtype", "GPT accepted",
        "Qwen category", "Qwen subtype", "Qwen accepted",
        "Qwen local repairs", "Notes / failure",
    ]
    add_title(details, "Actual Paired Results", len(headers))
    details.append(headers)
    style_header(details, 2, len(headers))
    details.freeze_panes = "A3"
    details.auto_filter.ref = f"A2:{get_column_letter(len(headers))}{len(references) + 2}"

    widths = (5, 19, 38, 18, 22, 18, 22, 14, 18, 22, 15, 42, 28)
    for column, width in enumerate(widths, 1):
        details.column_dimensions[get_column_letter(column)].width = width

    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        for index, reference in enumerate(references, 1):
            item_id = reference["item_id"]
            baseline = baseline_results[item_id]
            candidate = candidate_results[item_id]
            baseline_prediction = prediction(baseline)
            candidate_prediction = prediction(candidate)
            notes = []
            if baseline.get("status") != "succeeded":
                notes.append(f"GPT: {(baseline.get('error') or {}).get('type', 'failed')}")
            if candidate.get("status") != "succeeded":
                notes.append(f"Qwen: {(candidate.get('error') or {}).get('type', 'failed')}")
            row = index + 2
            values = [
                index, "", item_id,
                reference["production"].get("category"),
                reference["production"].get("subtype"),
                baseline_prediction.get("category"), baseline_prediction.get("subtype"),
                "Yes" if baseline.get("status") == "succeeded" else "No",
                candidate_prediction.get("category"), candidate_prediction.get("subtype"),
                "Yes" if candidate.get("status") == "succeeded" else "No",
                ", ".join(candidate.get("text_repair_actions") or []),
                "; ".join(notes),
            ]
            for column, value in enumerate(values, 1):
                details.cell(row, column, value)
                details.cell(row, column).alignment = Alignment(
                    vertical="center", wrap_text=True,
                )
            for column in (8, 11):
                details.cell(row, column).fill = PatternFill(
                    "solid", fgColor=GREEN if details.cell(row, column).value == "Yes" else RED,
                )
            image_matches = sorted(previews.glob(f"*-{item_id}.jpg"))
            if image_matches:
                thumbnail_path = temporary_path / f"{item_id}.jpg"
                with Image.open(image_matches[0]) as opened:
                    image = ImageOps.exif_transpose(opened).convert("RGB")
                    image.thumbnail((120, 120), Image.Resampling.LANCZOS)
                    image.save(thumbnail_path, "JPEG", quality=85)
                drawing = ExcelImage(thumbnail_path)
                drawing.width = image.width
                drawing.height = image.height
                details.add_image(drawing, f"B{row}")
            details.row_dimensions[row].height = 94

        output.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-run", type=Path, required=True)
    parser.add_argument("--candidate-run", type=Path, required=True)
    parser.add_argument("--previews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(
        baseline_run=args.baseline_run.resolve(),
        candidate_run=args.candidate_run.resolve(),
        previews=args.previews.resolve(),
        output=args.output.resolve(),
    )
    print(args.output.resolve())


if __name__ == "__main__":
    main()
