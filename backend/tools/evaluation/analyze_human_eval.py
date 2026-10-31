"""Create repeatable metrics and charts from the human-evaluation workbook.

The garment charts are parallel-category plots: each line is one garment, the
x-axis is the five label sources, and the y-axis is an intentionally ordered
categorical taxonomy.  Nearby positions mean labels are conceptually related;
they are not a claim that the labels have a numeric distance.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from openpyxl import load_workbook


SOURCES = ["Human 1", "Human 2", "Human 3", "baseline-picture", "baseline-vector"]
HUMAN_SOURCES = SOURCES[:3]
HUMAN_AGREEMENT_METHOD = "human agreement (mean pairwise; no ground truth)"
VERDICTS = ["Inappropriate", "Neutral", "Appropriate"]

# These orders make ambiguity interpretable in the line plots. For example,
# Everyday/Work and Travel/Vacation are adjacent rather than arbitrarily far apart.
LABEL_ORDERS = {
    "occasion": ["Wedding", "Evening", "Party", "Date", "Vacation", "Travel", "Lounge", "Workout", "Everyday", "Work"],
    "style": ["Sporty", "Casual", "Streetwear", "Edgy", "Minimalist", "Classic", "Preppy", "Business", "Formal", "Elegant", "Romantic", "Bohemian"],
    "season": ["Winter", "Spring/Fall", "Summer"],
}


def _valid(values: Iterable[object]) -> list[str]:
    return [str(value) for value in values if value not in (None, "")]


def majority_vote(labels: list[str]) -> tuple[str | None, bool]:
    """Return the majority label and whether the row is tied."""
    counts = Counter(_valid(labels))
    if not counts:
        return None, False
    highest = max(counts.values())
    winners = sorted(label for label, count in counts.items() if count == highest)
    return winners[0], len(winners) > 1


def fleiss_kappa(rows: list[list[str]]) -> float | None:
    """Fleiss' kappa for complete three-rater categorical rows."""
    if not rows:
        return None
    labels = sorted({label for row in rows for label in row})
    rater_count = len(rows[0])
    if rater_count < 2:
        return None
    overall = Counter(label for row in rows for label in row)
    observed = sum(
        sum(count * (count - 1) for count in Counter(row).values()) / (rater_count * (rater_count - 1))
        for row in rows
    ) / len(rows)
    expected = sum((overall[label] / (len(rows) * rater_count)) ** 2 for label in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def cohen_kappa(left: list[str], right: list[str]) -> float | None:
    if not left or len(left) != len(right):
        return None
    observed = sum(a == b for a, b in zip(left, right)) / len(left)
    left_counts, right_counts = Counter(left), Counter(right)
    expected = sum((left_counts[label] / len(left)) * (right_counts[label] / len(right)) for label in set(left_counts) | set(right_counts))
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def model_metrics(reference: list[str], prediction: list[str], labels: list[str]) -> dict[str, float]:
    """Macro metrics avoid letting a dominant label inflate accuracy."""
    accuracy = sum(a == b for a, b in zip(reference, prediction)) / len(reference)
    recalls, f1_scores = [], []
    for label in labels:
        true_positive = sum(a == label and b == label for a, b in zip(reference, prediction))
        false_positive = sum(a != label and b == label for a, b in zip(reference, prediction))
        false_negative = sum(a == label and b != label for a, b in zip(reference, prediction))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        recalls.append(recall)
        f1_scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return {
        "accuracy": accuracy,
        "balanced_accuracy": sum(recalls) / len(recalls),
        "macro_f1": sum(f1_scores) / len(f1_scores),
        "cohen_kappa": cohen_kappa(reference, prediction) or 0.0,
    }


def occasion_labels(value: str) -> set[str]:
    labels = {label.strip() for label in value.split(",") if label.strip()}
    unknown = labels - set(LABEL_ORDERS["occasion"])
    if unknown:
        raise ValueError(f"Unknown occasion labels: {sorted(unknown)}")
    return labels


def occasion_hit_metrics(reference: list[str], prediction: list[str]) -> dict:
    """Any overlap is a hit; extra predictions are not penalised by this metric."""
    if len(reference) != len(prediction):
        raise ValueError("Reference and prediction lengths differ")
    actual = [occasion_labels(value) for value in reference]
    predicted = [occasion_labels(value) for value in prediction]
    hits = [bool(a & b) for a, b in zip(actual, predicted)]
    per_label = [sum(hit for a, hit in zip(actual, hits) if label in a) / sum(label in a for a in actual)
                 for label in LABEL_ORDERS["occasion"] if any(label in a for a in actual)]
    return {"hits": sum(hits), "hit_rate": sum(hits) / len(hits) if hits else None,
            "balanced_hit_rate": sum(per_label) / len(per_label) if per_label else None,
            "mean_prediction_count": sum(map(len, predicted)) / len(predicted) if predicted else None}


def pairwise_agreement_metrics(left: list[str], right: list[str], labels: list[str]) -> dict[str, float]:
    """Symmetric inter-rater metrics; neither rater is treated as correct."""
    forward = model_metrics(left, right, labels)
    reverse = model_metrics(right, left, labels)
    return {key: (forward[key] + reverse[key]) / 2 for key in forward}


def _sheet_rows(sheet, columns: list[int], first_row: int = 3) -> list[list[str]]:
    return [[str(sheet.cell(row, column).value) if sheet.cell(row, column).value not in (None, "") else "" for column in columns] for row in range(first_row, sheet.max_row + 1)]


def plot_garment_paths(rows: list[list[str]], label_type: str, output_path: Path, sources=None) -> None:
    sources = sources or SOURCES
    order = LABEL_ORDERS[label_type]
    positions = {label: index for index, label in enumerate(order)}
    figure, axis = plt.subplots(figsize=(11, max(5.5, len(order) * 0.52)))
    source_positions = np.arange(len(SOURCES))
    consensus_colors = {label: plt.cm.tab20(index % 20) for index, label in enumerate(order)}
    plotted = 0
    for index, source_labels in enumerate(rows):
        label_sets = [occasion_labels(label) if label_type == "occasion" else {label} for label in source_labels]
        if any(not labels or any(label not in positions for label in labels) for labels in label_sets):
            continue
        consensus, _ = majority_vote(source_labels[:3])
        # Fixed tiny jitter lets many identical labels remain visible without
        # changing their category meaning.
        jitter = ((index % 9) - 4) * 0.018
        color = consensus_colors.get(consensus, "#999999")
        for x, labels in enumerate(label_sets):
            axis.scatter([x] * len(labels), [positions[label] + jitter for label in labels], color=color, alpha=0.25, s=7)
        for x in range(len(label_sets) - 1):
            for left in label_sets[x]:
                for right in label_sets[x + 1]:
                    axis.plot([x, x + 1], [positions[left] + jitter, positions[right] + jitter], color=color, alpha=0.12, linewidth=0.6)
        plotted += 1
    axis.set_xticks(source_positions, sources, rotation=10)
    axis.set_yticks(range(len(order)), order)
    axis.set_xlim(-0.15, len(SOURCES) - 0.85)
    axis.set_ylim(-0.45, len(order) - 0.55)
    axis.grid(axis="y", alpha=0.22)
    axis.set_title(f"Garment-label paths: {label_type.title()} ({plotted} garments)", weight="bold", loc="left")
    axis.set_xlabel("Label source")
    axis.set_ylabel("Ordered label taxonomy (adjacency represents conceptual similarity)")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_confusion(reference: list[str], prediction: list[str], labels: list[str], title: str, axis) -> None:
    matrix = np.zeros((len(labels), len(labels)), dtype=int)
    lookup = {label: index for index, label in enumerate(labels)}
    for actual, predicted in zip(reference, prediction):
        matrix[lookup[actual], lookup[predicted]] += 1
    normalised = np.divide(matrix, matrix.sum(axis=1, keepdims=True), out=np.zeros_like(matrix, dtype=float), where=matrix.sum(axis=1, keepdims=True) != 0)
    image = axis.imshow(normalised, vmin=0, vmax=1, cmap="Blues")
    for row in range(len(labels)):
        for column in range(len(labels)):
            axis.text(column, row, f"{matrix[row, column]}\n{normalised[row, column]:.0%}", ha="center", va="center", fontsize=8)
    axis.set_xticks(range(len(labels)), labels, rotation=28, ha="right")
    axis.set_yticks(range(len(labels)), labels)
    axis.set_xlabel("Model label")
    axis.set_ylabel("Human-majority label")
    axis.set_title(title, fontsize=10, weight="bold")
    return image


def plot_outfit_confusions(tasks: dict[str, dict], output_path: Path) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(12, 10))
    for axis, (task_name, task) in zip(axes.flat, tasks.items()):
        plot_confusion(task["reference"], task["picture"], VERDICTS, f"{task_name}: baseline-picture", axis)
    # Replace lower row with vector so the grid groups methods by task in reading order.
    for axis, task_name in zip(axes[1], list(tasks)):
        task = tasks[task_name]
        axis.clear()
        plot_confusion(task["reference"], task["vector"], VERDICTS, f"{task_name}: baseline-vector", axis)
    figure.suptitle(
        "Outfit judgment agreement with human-majority labels\nDarker cells indicate a larger within-row proportion; each cell also shows count and percentage.",
        weight="bold",
        x=0.02,
        ha="left",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    figure.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot_outfit_distributions(tasks: dict[str, dict], output_path: Path) -> None:
    sources = ["Human majority", "baseline-picture", "baseline-vector"]
    colors = {"Inappropriate": "#D95F5F", "Neutral": "#E6B44B", "Appropriate": "#4E9F6D"}
    figure, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for axis, (task_name, task) in zip(axes, tasks.items()):
        values = [task["reference"], task["picture"], task["vector"]]
        bottom = np.zeros(len(sources))
        for label in VERDICTS:
            proportions = np.array([labels.count(label) / len(labels) for labels in values])
            axis.bar(sources, proportions, bottom=bottom, label=label, color=colors[label])
            bottom += proportions
        axis.set_title(task_name, weight="bold")
        axis.set_ylim(0, 1)
        axis.set_ylabel("Proportion of 100 outfits")
        axis.tick_params(axis="x", rotation=18)
    axes[1].legend(loc="upper right")
    figure.suptitle("Verdict distribution: calibration check", weight="bold", x=0.02, ha="left")
    figure.tight_layout()
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def plot_metrics_overview(metrics_path: Path, output_path: Path) -> None:
    """Visualise the CSV's main metrics without mixing incomparable measures."""
    with metrics_path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    human_rows = [row for row in rows if row["method"] == HUMAN_AGREEMENT_METHOD]
    outfit_rows = [
        row
        for row in rows
        if row["scope"].startswith("outfit_")
        and row["method"] in {HUMAN_AGREEMENT_METHOD, "baseline-picture vs human-majority", "baseline-vector vs human-majority"}
    ]
    figure, axes = plt.subplots(2, 1, figsize=(13, 10))
    metric_names = ["accuracy", "balanced_accuracy", "macro_f1", "cohen_kappa"]
    metric_labels = ["Accuracy", "Balanced accuracy", "Macro-F1", "Cohen's kappa"]
    agreement_labels = ["Raw agreement", "Mean per-label agreement", "Macro-F1 agreement", "Cohen's kappa"]
    colors = ["#2B6CB0", "#38A169", "#D69E2E", "#805AD5"]

    x = np.arange(len(human_rows))
    width = 0.19
    for index, (metric, label, color) in enumerate(zip(metric_names, agreement_labels, colors)):
        axes[0].bar(x + (index - 1.5) * width, [float(row[metric]) for row in human_rows], width, label=label, color=color)
    axes[0].set_xticks(x, [row["scope"].replace("garment_", "Garment: ").replace("outfit_", "Outfit: ") for row in human_rows], rotation=12, ha="right")
    axes[0].set_ylim(0, 1)
    axes[0].set_ylabel("Score")
    axes[0].set_title("Human agreement by evaluation task", weight="bold", loc="left")
    axes[0].legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    axes[0].grid(axis="y", alpha=0.2)

    method_order = [HUMAN_AGREEMENT_METHOD, "baseline-picture vs human-majority", "baseline-vector vs human-majority"]
    method_labels = ["Human pairwise mean", "baseline-picture", "baseline-vector"]
    group_labels = []
    values: list[list[float]] = []
    for scope in ["outfit_Wearable", "outfit_Aesthetic"]:
        by_method = {row["method"]: row for row in outfit_rows if row["scope"] == scope}
        for method, label in zip(method_order, method_labels):
            group_labels.append(f"{scope.replace('outfit_', '')}\n{label}")
            values.append([float(by_method[method][metric]) for metric in metric_names])
    x = np.arange(len(group_labels))
    for index, (metric, label, color) in enumerate(zip(metric_names, metric_labels, colors)):
        axes[1].bar(x + (index - 1.5) * width, [row[index] for row in values], width, label=label, color=color)
    axes[1].set_xticks(x, group_labels)
    axes[1].set_ylim(-0.1, 1)
    axes[1].set_ylabel("Score")
    axes[1].set_title("Outfit judgment: models compared with human consistency", weight="bold", loc="left")
    axes[1].grid(axis="y", alpha=0.2)
    figure.suptitle("Evaluation metric overview", fontsize=16, weight="bold", x=0.02, ha="left")
    figure.tight_layout(rect=(0, 0.03, 1, 0.96))
    figure.savefig(output_path, dpi=180)
    plt.close(figure)


def write_method_notes(path: Path) -> None:
    path.write_text(
        "# Evaluation Metrics\n\n"
        "## Human agreement\n"
        "- **Coverage**: completed cells / expected cells. It shows whether a metric uses the full intended sample.\n"
        "- **Unanimous rate**: `# rows where all 3 humans agree / # complete rows`. It identifies clear versus inherently ambiguous examples.\n"
        "- **Fleiss' kappa**: `(P_bar - P_e) / (1 - P_e)`, where `P_bar` is observed multi-rater agreement and `P_e` is agreement expected from label frequencies. It discounts agreement caused by a common label.\n"
        "- **Pairwise Cohen's kappa**: `(p_o - p_e) / (1 - p_e)`. It is the two-rater counterpart, useful for identifying a systematically different annotator.\n\n"
        "## Model agreement with the human-majority label\n"
        "- **Accuracy**: `correct / total`. Report it, but do not optimise it alone because one class can dominate.\n"
        "- **Balanced accuracy**: mean recall across classes. It gives Inappropriate, Neutral, and Appropriate equal importance.\n"
        "- **Macro-F1**: mean of per-class F1 scores, where `F1 = 2 * precision * recall / (precision + recall)`. This is the primary model metric in this workbook.\n"
        "- **Cohen's kappa**: agreement with human majority after correcting for chance agreement from the label distribution.\n\n"
        "For rows named `human agreement (mean pairwise; no ground truth)`, the first three columns are agreement measures: raw agreement, mean per-label agreement, and macro-F1 agreement. They are averaged across Human 1 vs 2, Human 1 vs 3, and Human 2 vs 3; no annotator is treated as privileged ground truth.\n\n"
        "For `baseline-* vs human-majority` rows, the reference is the majority vote of all three humans. A 1-1-1 split has no majority and is excluded from the machine metric's `n`.\n\n"
        "## Occasion multi-label hit rule\n"
        "For Occasion only, a machine result is a hit when its comma-separated label set contains the human-majority occasion. Extra predicted labels are not penalised. Three-way human ties and rows missing either machine result are excluded; both models use the same eligible rows. Human-human agreement is unchanged.\n\n"
        "`hit_rate = hits / n`; `balanced_hit_rate` averages hit rates across human-majority classes present in the sample. `mean_prediction_count` shows how many labels each model emits. Single-label accuracy, Macro-F1 and Cohen kappa are intentionally blank for these machine rows. Predicting all labels would achieve 100% hits, so this metric does not measure precision.\n\n"
        "The source names come from each workbook column: current-recognition-model is the saved vision-model result, not a vector baseline. Other tasks retain their original metrics.\n\n"
        "## Interpretation guardrail\n"
        "This workbook's outfit rows are randomly constructed candidate outfits. The outfit metrics measure whether a method judges a supplied outfit like humans do; they do **not** measure how good its generated recommendations are. A recommendation-quality study should have each method generate outfits for the same contexts, then collect blinded human wearable/aesthetic ratings.\n"
    )


def write_metrics(path: Path, garment_tasks: dict[str, list[list[str]]], outfit_tasks: dict[str, dict], garment_sources=None) -> None:
    rows: list[dict[str, object]] = []

    def add_human_agreement(scope: str, human_rows: list[list[str]], labels: list[str]) -> None:
        """Summarise pairwise human metrics without pretending one human is truth."""
        pair_metrics = []
        for left, right in combinations(range(3), 2):
            reference = [row[left] for row in human_rows]
            prediction = [row[right] for row in human_rows]
            metrics = pairwise_agreement_metrics(reference, prediction, labels)
            pair_metrics.append(metrics)
            pair_row = {"scope": scope, "method": f"{HUMAN_SOURCES[left]} vs {HUMAN_SOURCES[right]}", "n": len(human_rows)}
            pair_row.update(metrics)
            rows.append(pair_row)
        # These values are averages over the three pairwise comparisons, not a
        # score against a privileged human "ground truth".
        rows.append(
            {
                "scope": scope,
                "method": HUMAN_AGREEMENT_METHOD,
                "n": len(human_rows),
                "accuracy": sum(metric["accuracy"] for metric in pair_metrics) / len(pair_metrics),
                "balanced_accuracy": sum(metric["balanced_accuracy"] for metric in pair_metrics) / len(pair_metrics),
                "macro_f1": sum(metric["macro_f1"] for metric in pair_metrics) / len(pair_metrics),
                "cohen_kappa": sum(metric["cohen_kappa"] for metric in pair_metrics) / len(pair_metrics),
                "unanimous_rate": sum(len(set(row)) == 1 for row in human_rows) / len(human_rows),
                "fleiss_kappa": fleiss_kappa(human_rows),
            }
        )

    for name, labels_by_source in garment_tasks.items():
        complete = [row for row in labels_by_source if all(row[:3])]
        human_rows = [row[:3] for row in complete]
        add_human_agreement(f"garment_{name}", human_rows, LABEL_ORDERS[name])
        # A tied 1-1-1 human row has no majority label, so it is excluded from
        # model scoring rather than broken arbitrarily.
        majority_rows = []
        for row in complete:
            majority, tied = majority_vote(row[:3])
            if not tied and row[3] and row[4]:
                majority_rows.append((majority, row[3], row[4]))
        for index, method in enumerate(("picture", "vector"), start=1):
            reference = [row[0] for row in majority_rows]
            prediction = [row[index] for row in majority_rows]
            source = garment_sources[name][index + 2] if garment_sources else f"baseline-{method}"
            metric_row = {"scope": f"garment_{name}", "method": f"{source} vs human-majority", "n": len(reference)}
            if name == "occasion":
                metric_row.update(occasion_hit_metrics(reference, prediction))
                metric_row["excluded_missing_human"] = len(labels_by_source) - len(complete)
                metric_row["excluded_no_majority"] = sum(majority_vote(row[:3])[1] for row in complete)
                metric_row["excluded_missing_prediction"] = sum(not majority_vote(row[:3])[1] and (not row[3] or not row[4]) for row in complete)
            else:
                metric_row.update(model_metrics(reference, prediction, LABEL_ORDERS[name]))
            rows.append(metric_row)
    for name, task in outfit_tasks.items():
        human_rows = task["human_rows"]
        add_human_agreement(f"outfit_{name}", human_rows, VERDICTS)
        for method in ("picture", "vector"):
            row = {"scope": f"outfit_{name}", "method": f"baseline-{method} vs human-majority", "n": len(task["reference"])}
            row.update(model_metrics(task["reference"], task[method], VERDICTS))
            rows.append(row)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Keep the spreadsheet readable while preserving full precision in
            # the underlying calculation code.
            writer.writerow({key: f"{value:.3f}" if isinstance(value, float) else value for key, value in row.items()})


def write_occasion_hit_report(sheet, rows, sources, output_dir):
    audit = []
    for index, row in enumerate(rows, start=3):
        majority, tied = majority_vote(row[:3])
        status = "included"
        if not all(row[:3]):
            status = "missing human label"
        elif tied:
            status = "no human majority"
        elif not all(row[3:]):
            status = "missing model prediction"
        entry = {"code": sheet.cell(index, 2).value, "item_id": sheet.cell(index, 3).value,
                 "human_1": row[0], "human_2": row[1], "human_3": row[2],
                 "human_majority": majority if not tied else "", "status": status}
        for offset, source in enumerate(sources[3:], start=3):
            entry[source] = row[offset]
            entry[source + " hit"] = int(bool(occasion_labels(row[offset]) & occasion_labels(majority))) if status == "included" else ""
        audit.append(entry)
    with (output_dir / "occasion_hits_by_item.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit[0]))
        writer.writeheader()
        writer.writerows(audit)
    included = [row for row in audit if row["status"] == "included"]
    figure, axes = plt.subplots(1, 2, figsize=(12, 6), gridspec_kw={"width_ratios": [1, 2]})
    counts = [sum(row[source + " hit"] for row in included) for source in sources[3:]]
    n = len(included)
    axes[0].bar(sources[3:], [count / n if n else 0 for count in counts], color=["#2B6CB0", "#38A169"])
    for x, count in enumerate(counts):
        axes[0].text(x, count / n + .02 if n else .02, f"{count}/{n}" + (f" ({count/n:.1%})" if n else ""), ha="center")
    axes[0].set_ylim(0, 1.15)
    axes[0].tick_params(axis="x", rotation=15)
    axes[0].set_title("Occasion hit rate")
    labels = [label for label in LABEL_ORDERS["occasion"] if any(row["human_majority"] == label for row in included)]
    matrix = np.array([[sum(row[source + " hit"] for row in included if row["human_majority"] == label) / sum(row["human_majority"] == label for row in included) for source in sources[3:]] for label in labels])
    if labels:
        axes[1].imshow(matrix, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        axes[1].set_xticks([0, 1], sources[3:], rotation=15)
        axes[1].set_yticks(range(len(labels)), labels)
        for y, label in enumerate(labels):
            total = sum(row["human_majority"] == label for row in included)
            for x, source in enumerate(sources[3:]):
                hits = sum(row[source + " hit"] for row in included if row["human_majority"] == label)
                axes[1].text(x, y, f"{hits}/{total} ({hits/total:.0%})", ha="center", va="center", color="white" if hits/total > .65 else "black")
    axes[1].set_title("Hit matrix by human-majority occasion")
    figure.suptitle(f"Any predicted occasion matching the human majority is a hit\n{n} eligible garments; {len(audit)-n} excluded")
    figure.tight_layout()
    figure.savefig(output_dir / "occasion_hit_rates.png", dpi=180)
    plt.close(figure)


def run(workbook_path: Path, output_dir: Path) -> None:
    workbook = load_workbook(workbook_path, data_only=True)
    garment = workbook["Garment Labels"]
    outfits = workbook["Outfit Judgments"]
    output_dir.mkdir(parents=True, exist_ok=True)

    garment_columns = {"occasion": [4, 5, 6, 7, 8], "style": [9, 10, 11, 12, 13], "season": [14, 15, 16, 17, 18]}
    garment_tasks = {name: _sheet_rows(garment, columns) for name, columns in garment_columns.items()}
    garment_sources = {name: [str(garment.cell(2, column).value) for column in columns] for name, columns in garment_columns.items()}
    for name, rows in garment_tasks.items():
        plot_garment_paths(rows, name, output_dir / f"garment_paths_{name}.png", garment_sources[name])
    write_occasion_hit_report(garment, garment_tasks["occasion"], garment_sources["occasion"], output_dir)

    outfit_tasks: dict[str, dict] = {}
    for name, columns in {"Wearable": [9, 10, 11, 12, 13], "Aesthetic": [14, 15, 16, 17, 18]}.items():
        complete = [row for row in _sheet_rows(outfits, columns) if all(row)]
        majority_rows = []
        for row in complete:
            majority, tied = majority_vote(row[:3])
            if not tied:
                majority_rows.append((row, majority))
        outfit_tasks[name] = {
            "human_rows": [row[:3] for row, _ in majority_rows],
            "reference": [majority for _, majority in majority_rows],
            "picture": [row[3] for row, _ in majority_rows],
            "vector": [row[4] for row, _ in majority_rows],
        }

    write_metrics(output_dir / "metrics.csv", garment_tasks, outfit_tasks, garment_sources)
    write_method_notes(output_dir / "metrics_and_interpretation.md")
    plot_metrics_overview(output_dir / "metrics.csv", output_dir / "metrics_overview.png")
    plot_outfit_confusions(outfit_tasks, output_dir / "outfit_confusion_matrices.png")
    plot_outfit_distributions(outfit_tasks, output_dir / "outfit_verdict_distributions.png")
    print(f"Analysis written to: {output_dir.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse a closet human-evaluation workbook.")
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or args.workbook.parent / "analysis"
    run(args.workbook, output_dir)


if __name__ == "__main__":
    main()
