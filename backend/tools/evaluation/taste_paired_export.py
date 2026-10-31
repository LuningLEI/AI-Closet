"""Export a matched before/after taste evaluation without new model calls.

The shared no-taste condition is reused as the Before control for every
persona because the production system has no persona-specific evidence before
learning. Existing persona runs provide the After conditions. This module is
read-only with respect to production and the source evaluation artifacts.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from app.models.domain import ClothingItemRecord
from app.outfits.models import VisualReview
from app.outfits.store import LocalOutfitStore
from app.services.taste_profile import outfit_taste_score
from tools.evaluation.taste_end_to_end_evaluation import (
    PERSONAS,
    _photos_from_folder,
    _preview,
    persona_sources,
    preference_text,
)


def _feedback_window(persona: dict) -> tuple[int, str]:
    sources = persona_sources(persona)
    if not sources:
        return 0, "No feedback"
    dates = sorted(datetime.fromisoformat(row["created_at"]).date() for row in sources)
    elapsed = (dates[-1] - dates[0]).days
    return len(sources), (
        f"{dates[0].isoformat()} to {dates[-1].isoformat()} "
        f"({elapsed}-day span; 6-day inclusive window; 23-28 days old at evaluation)"
    )


def _load_records(source: Path) -> dict[str, ClothingItemRecord]:
    return {
        row["id"]: ClothingItemRecord.model_validate(row)
        for row in json.loads((source / "wardrobe.json").read_text())
    }


def _usage(store: LocalOutfitStore, uid: str) -> dict:
    reports = store.run_report(uid)
    return reports[0] if reports else {}


def _condition_rows(
    source: Path,
    store: LocalOutfitStore,
    items: dict[str, ClothingItemRecord],
    persona: dict,
    stage: str,
    profile: dict,
) -> list[dict]:
    uid = "taste-e2e-p00" if stage == "Before" else f"taste-e2e-{persona['id'].lower()}"
    usage = _usage(store, uid)
    rows = []
    for index, record in enumerate(sorted(store.evaluations(uid), key=lambda row: row["id"]), start=1):
        payload = record["payload"]
        members = [items[item_id] for item_id in payload["item_ids"]]
        review = VisualReview.model_validate(payload["visual_review"])
        preview = source / "previews" / f"{('P00' if stage == 'Before' else persona['id'])}_{index:02d}.jpg"
        if not preview.exists():
            _preview(payload["item_ids"], _photos_from_folder(source), preview)
        rows.append({
            "persona": persona,
            "stage": stage,
            "record": record,
            "members": members,
            "review": review,
            "preview": preview,
            "target_score": outfit_taste_score(members, profile),
            "usage": usage,
        })
    return rows


def export(source: Path, output: Path) -> Path:
    manifest = json.loads((source / "manifest.json").read_text())
    profiles = json.loads((source / "profiles.json").read_text())
    store = LocalOutfitStore(source / "evaluation.sqlite3")
    items = _load_records(source)
    output.mkdir(parents=True, exist_ok=True)

    rows = []
    for persona in PERSONAS:
        after_profile = profiles[f"taste-e2e-{persona['id'].lower()}"]
        rows.extend(_condition_rows(source, store, items, persona, "Before", after_profile))
        rows.extend(_condition_rows(source, store, items, persona, "After", after_profile))

    workbook = Workbook()
    method = workbook.active
    method.title = "Original Parameter Simulation"
    method.merge_cells("A1:D1")
    method["A1"] = "How the current Taste Profile parameters were selected"
    method["A1"].font = Font(bold=True, color="FFFFFF", size=16)
    method["A1"].fill = PatternFill("solid", fgColor="1F4E78")
    method["A1"].alignment = Alignment(horizontal="center", vertical="center")
    method.row_dimensions[1].height = 32
    method_rows = [
        ["Research question", "Which deterministic Taste Profile defaults learn quickly, rank outfits accurately, tolerate noisy feedback, and avoid score saturation?", "", ""],
        ["Simulation subject", "Synthetic users and a synthetic catalog; this was a parameter-learning simulation, not an outfit-image generation experiment.", "", ""],
        ["Step", "Method", "Controlled design", "Purpose"],
        ["1. Create hidden taste", "Assign each virtual user an unobserved oracle preference over style, color, pattern, occasion, category, subtype, warmth, and formality.", "Small seed-specific variation", "Provides known ground truth for evaluation."],
        ["2. Present candidates", "Rank synthetic outfit candidates using the tested Taste configuration.", "Same candidate catalog and random seeds across parameter variants", "Makes configuration comparisons paired and fair."],
        ["3. Simulate behavior", "Generate Like, Wear, Personal Outfit, reason-scoped Not for Me, or no-feedback events from oracle utility.", "Feedback error depends on scenario", "Models positive, negative, missing, and noisy signals."],
        ["4. Run production reducer", "Replay every event through the real production reduce_sources implementation.", "No model training or LLM call", "Tests the exact deterministic learning logic used by the app."],
        ["5. Re-rank and measure", "Use the updated feature weights to rank the next candidate set and compare it with the oracle ranking.", "Repeated for 120 feedback opportunities", "Measures learning speed and downstream ranking quality."],
        ["6. Search parameters", "First vary one factor at a time, then run a two-stage joint search across 48 candidate configurations.", "Paired Monte Carlo seeds for every configuration", "Separates parameter effects before selecting a combined default."],
        ["", "", "", ""],
        ["Simulation scale", "30 virtual users per parameter/scenario pair", "120 feedback opportunities per user; one opportunity every 3 simulated days", "Approximately one simulated year of interaction."],
        ["Scenario", "Stable preference", "5% feedback error; no preference change", "Tests normal learning and final ranking."],
        ["Scenario", "Noisy feedback", "20% feedback error", "Tests robustness to inconsistent user actions."],
        ["Scenario", "Preference drift", "Hidden preference changes halfway through", "Tests recovery when a user's taste changes."],
        ["", "", "", ""],
        ["Metric", "Definition", "Desired direction", "Role in selection"],
        ["NDCG@10", "Agreement between the learned top-10 ranking and the oracle top-10 ranking.", "Higher", "Primary ranking-quality metric."],
        ["Mean regret", "Oracle utility lost by showing the learned recommendation instead of the best available candidate.", "Lower", "Measures practical recommendation loss."],
        ["Activation step", "Number of feedback opportunities before evidence first affects ranking or generation.", "Lower, while remaining stable", "Measures cold-start speed."],
        ["Preference alignment", "Cosine similarity between eligible learned feature weights and hidden oracle preference weights.", "Higher", "Checks whether the reducer learns the correct direction."],
        ["Score saturation", "Share of candidates reaching the ±20 personalization score bound.", "Lower", "Protects ranking resolution; v1 reached 100%."],
        ["Drift recovery", "Post-change opportunities needed to regain at least 0.50 preference alignment.", "Lower", "Measures adaptation to changing tastes."],
        ["", "", "", ""],
        ["Selection result", "The search selected threshold 2, exploration 15%, half-life 270 days, decay floor 0%, prior 2.5, and personalization scale 0.5.", "Promoted as taste-profile-v2 on 2026-10-29", "The exact old/new values are on Sheet 2."],
        ["Interpretation limit", "The simulation validates mechanics under explicit synthetic assumptions. It does not prove real-user satisfaction.", "Requires real-feedback replay and eventual online A/B testing", "Prevents overclaiming simulation results."],
    ]
    for row in method_rows:
        method.append(row)
    for row_number in (4, 17):
        for cell in method[row_number]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="5B9BD5")
            cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row_number in range(2, method.max_row + 1):
        method.cell(row_number, 1).font = Font(bold=True)
        for cell in method[row_number]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for column, width in zip("ABCD", [27, 75, 60, 48]):
        method.column_dimensions[column].width = width
    method.freeze_panes = "A4"

    review_sheet = workbook.create_sheet("Before-After Review")
    headers = [
        "Persona", "Learning stage", "Feedback events", "Feedback window", "Taste passed to pipeline",
        "Target preferences", "Target avoids", "Outfit preview", "Items", "Pipeline accepted",
        "Post-hoc target alignment", "Core wearability", "Core thermal", "Core color/pattern",
        "Core occasion", "Generation reason", "Input tokens (source run)", "Output tokens (source run)",
        "Human preference match (1-5)", "Would this persona wear it? (Y/N)",
        "Human structurally wearable? (Y/N)", "Human notes",
    ]
    review_sheet.append(headers)
    for cell in review_sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    for row_index, data in enumerate(rows, start=2):
        persona = data["persona"]
        count, window = _feedback_window(persona)
        stage = data["stage"]
        review = data["review"]
        usage = data["usage"]
        labels = "\n".join(
            f"{item.category} / {item.subtype or 'Unknown'} / {item.color}"
            for item in data["members"]
        )
        review_sheet.append([
            f"{persona['id']} · {persona['name']}", stage, 0 if stage == "Before" else count,
            "No feedback" if stage == "Before" else window, "No" if stage == "Before" else "Yes",
            preference_text(persona, "prefer"), preference_text(persona, "avoid"), "", labels,
            "Yes" if review.core.passes() else "No", round(data["target_score"], 4),
            review.core.wearability.verdict, review.core.thermal.verdict,
            review.core.color_pattern.verdict, review.core.occasion.verdict,
            data["record"]["payload"].get("generation_reason"), usage.get("input_tokens"),
            usage.get("output_tokens"), "", "", "", "",
        ])
        image = ExcelImage(data["preview"])
        image.width = min(750, 150 * len(data["members"]))
        image.height = 174
        review_sheet.add_image(image, f"H{row_index}")
        review_sheet.row_dimensions[row_index].height = 135

    widths = {
        "A": 27, "B": 15, "C": 16, "D": 45, "E": 22, "F": 45, "G": 40, "H": 95,
        "I": 38, "J": 18, "K": 23, "L": 17, "M": 15, "N": 19, "O": 16, "P": 50,
        "Q": 20, "R": 20, "S": 26, "T": 32, "U": 30, "V": 40,
    }
    for column, width in widths.items():
        review_sheet.column_dimensions[column].width = width
    review_sheet.freeze_panes = "A2"
    review_sheet.auto_filter.ref = f"A1:V{review_sheet.max_row}"
    rating_validation = DataValidation(type="whole", operator="between", formula1="1", formula2="5", allow_blank=True)
    yes_no_validation = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    review_sheet.add_data_validation(rating_validation)
    review_sheet.add_data_validation(yes_no_validation)
    rating_validation.add(f"S2:S{review_sheet.max_row}")
    yes_no_validation.add(f"T2:U{review_sheet.max_row}")
    for row in review_sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    parameters = workbook.create_sheet("Previous vs Current Params")
    parameters.merge_cells("A1:E1")
    parameters["A1"] = (
        "Historical production defaults: taste-profile-v1 vs current taste-profile-v2. "
        "The outfit experiment itself holds v2 parameters constant and compares no Taste (Before) "
        "with learned Taste (After); it is not a v1-v2 generation comparison."
    )
    parameters["A1"].font = Font(bold=True, color="FFFFFF")
    parameters["A1"].fill = PatternFill("solid", fgColor="1F4E78")
    parameters["A1"].alignment = Alignment(wrap_text=True, vertical="center")
    parameters.row_dimensions[1].height = 48
    parameters.append(["Parameter", "Previous · v1", "Current · v2", "Change", "What it controls"])
    parameter_rows = [
        ["generation_evidence_threshold", 3, 2, "3 → 2", "Minimum repeated evidence before a feature can affect generation; lower activates earlier."],
        ["exploration_rate", "10%", "15%", "+5 percentage points", "Share of generated outfits reserved for valid candidates outside established positive evidence."],
        ["half_life_days", 180, 270, "+90 days", "How quickly old evidence decays; a longer half-life preserves stable preferences longer."],
        ["decay_floor", "30%", "0%", "−30 percentage points", "Minimum retained weight of very old evidence; zero lets stale preferences eventually disappear."],
        ["prior_strength", 5.0, 2.5, "5.0 → 2.5", "Shrinkage applied to sparse feature evidence; lower values allow observed evidence to gain confidence faster."],
        ["personalization_scale", 4.0, 0.5, "4.0 → 0.5", "Multiplier that converts learned feature weights into ranking score; lower scale prevents score saturation."],
        ["maximum_personalization_score", "±20", "±20", "Unchanged", "Hard bound on the total personalization adjustment applied to an outfit."],
    ]
    for row in parameter_rows:
        parameters.append(row)
    parameters.append([])
    parameters.append(["Version", "taste-profile-v1", "taste-profile-v2", "Promoted 2026-10-29", "v2 was selected by the two-stage synthetic parameter search."])
    for cell in parameters[2]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="5B9BD5")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in parameters.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for column, width in zip("ABCDE", [36, 22, 22, 25, 90]):
        parameters.column_dimensions[column].width = width
    parameters.freeze_panes = "A3"
    workbook.move_sheet(parameters, offset=-1)

    summary = workbook.create_sheet("Paired Main Results")
    summary_headers = [
        "Persona", "Feedback events", "Feedback window", "Before outfits", "After outfits",
        "Before preference (1-5)", "After preference (1-5)", "Preference delta",
        "Before would-wear rate", "After would-wear rate", "Would-wear delta",
        "Before wearable rate", "After wearable rate", "Wearable delta", "Conclusion / notes",
    ]
    summary.append(summary_headers)
    for cell in summary[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True)
    for row_index, persona in enumerate(PERSONAS, start=2):
        persona_key = f"{persona['id']} · {persona['name']}"
        count, window = _feedback_window(persona)
        summary.append([
            persona_key, count, window,
            f'=COUNTIFS(\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"Before")',
            f'=COUNTIFS(\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"After")',
            f'=IFERROR(AVERAGEIFS(\'Before-After Review\'!S:S,\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"Before"),"")',
            f'=IFERROR(AVERAGEIFS(\'Before-After Review\'!S:S,\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"After"),"")',
            f'=IF(OR(F{row_index}="",G{row_index}=""),"",G{row_index}-F{row_index})',
            f'=IFERROR(COUNTIFS(\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"Before",\'Before-After Review\'!T:T,"Y")/D{row_index},"")',
            f'=IFERROR(COUNTIFS(\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"After",\'Before-After Review\'!T:T,"Y")/E{row_index},"")',
            f'=IF(OR(I{row_index}="",J{row_index}=""),"",J{row_index}-I{row_index})',
            f'=IFERROR(COUNTIFS(\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"Before",\'Before-After Review\'!U:U,"Y")/D{row_index},"")',
            f'=IFERROR(COUNTIFS(\'Before-After Review\'!A:A,A{row_index},\'Before-After Review\'!B:B,"After",\'Before-After Review\'!U:U,"Y")/E{row_index},"")',
            f'=IF(OR(L{row_index}="",M{row_index}=""),"",M{row_index}-L{row_index})', "",
        ])
    summary.append([
        "Overall", "", "", "=SUM(D2:D11)", "=SUM(E2:E11)",
        '=IFERROR(AVERAGE(\'Before-After Review\'!S:S),"")',
        '=IFERROR(AVERAGEIFS(\'Before-After Review\'!S:S,\'Before-After Review\'!B:B,"After"),"")',
        '=IF(OR(F12="",G12=""),"",G12-F12)',
        '=IFERROR(COUNTIFS(\'Before-After Review\'!B:B,"Before",\'Before-After Review\'!T:T,"Y")/D12,"")',
        '=IFERROR(COUNTIFS(\'Before-After Review\'!B:B,"After",\'Before-After Review\'!T:T,"Y")/E12,"")',
        '=IF(OR(I12="",J12=""),"",J12-I12)',
        '=IFERROR(COUNTIFS(\'Before-After Review\'!B:B,"Before",\'Before-After Review\'!U:U,"Y")/D12,"")',
        '=IFERROR(COUNTIFS(\'Before-After Review\'!B:B,"After",\'Before-After Review\'!U:U,"Y")/E12,"")',
        '=IF(OR(L12="",M12=""),"",M12-L12)', "",
    ])
    # Overall Before preference must explicitly filter stage; overwrite the generic average above.
    summary["F12"] = '=IFERROR(AVERAGEIFS(\'Before-After Review\'!S:S,\'Before-After Review\'!B:B,"Before"),"")'
    for column, width in zip("ABCDEFGHIJKLMNO", [28, 16, 43, 16, 15, 23, 22, 18, 23, 22, 19, 21, 20, 18, 42]):
        summary.column_dimensions[column].width = width
    summary.freeze_panes = "A2"
    summary.conditional_formatting.add("H2:H12", ColorScaleRule(start_type="min", start_color="F8696B", end_type="max", end_color="63BE7B"))
    summary.conditional_formatting.add("K2:K11", ColorScaleRule(start_type="min", start_color="F8696B", end_type="max", end_color="63BE7B"))

    design = workbook.create_sheet("Experiment Design")
    design_rows = [
        ["Field", "Value"],
        ["Question", "Does the production recommendation pipeline better match each persona after Taste learning?"],
        ["Before", "0 feedback events; no Taste Profile passed to retrieval, generation, or visual review."],
        ["After", "5-7 synthetic feedback events; the learned per-user Taste Profile is used by the full pipeline."],
        ["Shared controls", "Same frozen 238-item wardrobe, anchor item, model/prompt/config version, and hard outfit rules."],
        ["Before reuse", "The same existing no-Taste output is reused for every persona because the system has no persona-specific evidence before learning."],
        ["Feedback timing", "Synthetic events dated 2026-10-01 through 2026-10-06; a 5-day elapsed span / 6-day inclusive window. At the 2026-10-29 evaluation, events were 23-28 days old."],
        ["Primary outcomes", "Human preference match (1-5) and would-wear rate."],
        ["Safety outcome", "Human structurally wearable rate; personalization should not reduce it."],
        ["New model calls", "0. All previews come from the completed source evaluation."],
        ["Source artifact", str(source.resolve())],
        ["Production writes", "None"],
    ]
    for row in design_rows:
        design.append(row)
    for cell in design[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    design.column_dimensions["A"].width = 24
    design.column_dimensions["B"].width = 115
    for row in design.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.calculation.calcMode = "auto"
    target = output / "taste_before_after_paired_results.xlsx"
    temporary = output / "taste_before_after_paired_results.tmp.xlsx"
    workbook.save(temporary)
    temporary.replace(target)
    metadata = {
        "created_at": datetime.now().astimezone().isoformat(),
        "source": str(source.resolve()),
        "personas": len(PERSONAS),
        "review_rows": len(rows),
        "stage_counts": dict(Counter(row["stage"] for row in rows)),
        "new_model_calls": 0,
        "production_writes": False,
    }
    (output / "paired_export_summary.json").write_text(json.dumps(metadata, indent=2))
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(export(args.source, args.output))


if __name__ == "__main__":
    main()
