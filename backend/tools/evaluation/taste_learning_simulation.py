"""Offline simulation for calibrating deterministic per-user Taste learning.

This module deliberately calls the production reducer. It uses synthetic users
whose latent preferences are known, so learning speed and parameter trade-offs
can be measured without database writes or model calls. Synthetic validity does
not replace a replay evaluation or an online experiment with real users.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.services.taste_profile import (
    DEFAULT_TASTE_LEARNING_CONFIG,
    TasteLearningConfig,
    reduce_sources,
    snapshot_features,
)
from tools.evaluation.paths import evaluation_path


@dataclass(frozen=True)
class SyntheticOutfit:
    identifier: str
    snapshot: dict
    features: dict[str, float]


@dataclass(frozen=True)
class Scenario:
    name: str
    feedback_error_rate: float = 0.05
    drift: bool = False


SCENARIOS = (
    Scenario("stable", feedback_error_rate=0.05),
    Scenario("noisy_feedback", feedback_error_rate=0.20),
    Scenario("preference_drift", feedback_error_rate=0.05, drift=True),
)


def parameter_variants() -> dict[str, TasteLearningConfig]:
    default = DEFAULT_TASTE_LEARNING_CONFIG
    return {
        "default": default,
        "evidence_2": replace(default, generation_evidence_threshold=2),
        "evidence_5": replace(default, generation_evidence_threshold=5),
        "exploration_0": replace(default, exploration_rate=0.0),
        "exploration_20": replace(default, exploration_rate=0.20),
        "half_life_90": replace(default, half_life_days=90.0),
        "half_life_365": replace(default, half_life_days=365.0),
        "prior_2_5": replace(default, prior_strength=2.5),
        "prior_10": replace(default, prior_strength=10.0),
        "scale_1": replace(default, personalization_scale=1.0),
        "scale_2": replace(default, personalization_scale=2.0),
        "signals_75": replace(default, personal_strength=1.5, wear_strength=1.125,
                              liked_strength=0.75, disliked_strength=-0.75),
        "signals_150": replace(default, personal_strength=3.0, wear_strength=2.25,
                               liked_strength=1.5, disliked_strength=-1.5),
        "decay_floor_0": replace(default, decay_floor=0.0),
        "decay_floor_50": replace(default, decay_floor=0.50),
    }


def _snapshot(identifier: str, style: str, color: str, pattern: str, occasion: str) -> dict:
    return {
        "items": [
            {"id": identifier + "-top", "category": "Tops", "subtype": "T-shirt",
             "color": color, "style": style, "occasion": occasion,
             "season": ["Spring", "Summer"], "pattern": pattern,
             "warmth_level": 2, "formality_score": 2 if occasion != "Work" else 4},
            {"id": identifier + "-bottom", "category": "Bottoms",
             "subtype": "Jeans" if style != "Sporty" else "Workout Leggings",
             "color": "Black" if color != "Black" else "Blue", "style": style,
             "occasion": occasion, "season": ["Spring", "Summer", "Fall"],
             "pattern": "Solid", "warmth_level": 2,
             "formality_score": 2 if occasion != "Work" else 4},
        ],
        "context": {"occasion": occasion},
        "outfit_vector": None,
    }


def synthetic_catalog() -> list[SyntheticOutfit]:
    outfits = []
    index = 0
    for style in ("Casual", "Minimal", "Romantic", "Sporty"):
        for color in ("Black", "Blue", "Pink", "Green"):
            for pattern in ("Solid", "Floral", "Striped"):
                for occasion in ("Everyday", "Work", "Date", "Workout"):
                    identifier = f"S{index:03d}"
                    snapshot = _snapshot(identifier, style, color, pattern, occasion)
                    outfits.append(SyntheticOutfit(identifier, snapshot, snapshot_features(snapshot)))
                    index += 1
    return outfits


PERSONAS = (
    {"style:minimal": 1.6, "color:black": 0.9, "color:blue": 0.4,
     "pattern:solid": 0.8, "pattern:floral": -1.1, "occasion:work": 0.4},
    {"style:romantic": 1.6, "color:pink": 0.9, "pattern:floral": 0.9,
     "color:black": -0.4, "occasion:date": 0.8},
    {"style:sporty": 1.7, "subtype:workout_leggings": 0.8,
     "occasion:workout": 1.1, "formality:high": -0.8, "pattern:floral": -0.5},
    {"style:casual": 1.2, "color:green": 0.7, "pattern:striped": 0.7,
     "occasion:everyday": 0.8, "formality:high": -0.5},
)


def _personalized_persona(seed: int, index: int) -> dict[str, float]:
    rng = random.Random(seed * 1009 + index * 9176)
    result = dict(PERSONAS[index % len(PERSONAS)])
    for key in list(result):
        result[key] *= rng.uniform(0.85, 1.15)
    return result


def _utility(outfit: SyntheticOutfit, preference: dict[str, float]) -> float:
    return sum(preference.get(key, 0.0) * value for key, value in outfit.features.items())


def _eligible_score(outfit: SyntheticOutfit, profile: dict, config: TasteLearningConfig) -> float:
    evidence = profile.get("feature_evidence") or {}
    weights = profile.get("feature_weights") or {}
    total = 0.0
    for key, value in outfit.features.items():
        row = evidence.get(key) or {}
        eligible = (not key.startswith(("item:", "shoe:", "accessory:")) and
                    (row.get("count", 0) >= config.generation_evidence_threshold or
                     row.get("wear_count", 0) >= config.generation_wear_threshold))
        if eligible:
            total += weights.get(key, 0.0) * value
    return max(-config.maximum_personalization_score,
               min(config.maximum_personalization_score, total * config.personalization_scale))


def _ndcg(outfits: list[SyntheticOutfit], predicted: dict[str, float],
          preference: dict[str, float], k: int = 10) -> float:
    utilities = {row.identifier: _utility(row, preference) for row in outfits}
    low, high = min(utilities.values()), max(utilities.values())
    scale = high - low or 1.0

    def gain(identifier: str) -> float:
        relevance = 4.0 * (utilities[identifier] - low) / scale
        return 2 ** relevance - 1

    predicted_order = sorted(outfits, key=lambda row: (-predicted[row.identifier], row.identifier))[:k]
    ideal_order = sorted(outfits, key=lambda row: (-utilities[row.identifier], row.identifier))[:k]
    dcg = sum(gain(row.identifier) / math.log2(position + 2)
              for position, row in enumerate(predicted_order))
    ideal = sum(gain(row.identifier) / math.log2(position + 2)
                for position, row in enumerate(ideal_order))
    return dcg / ideal if ideal else 1.0


def _alignment(profile: dict, preference: dict[str, float], config: TasteLearningConfig) -> float:
    learned = []
    truth = []
    evidence = profile.get("feature_evidence") or {}
    weights = profile.get("feature_weights") or {}
    for key, expected in sorted(preference.items()):
        row = evidence.get(key) or {}
        eligible = (row.get("count", 0) >= config.generation_evidence_threshold or
                    row.get("wear_count", 0) >= config.generation_wear_threshold)
        learned.append(weights.get(key, 0.0) if eligible else 0.0)
        truth.append(expected)
    denominator = math.sqrt(sum(value * value for value in learned) *
                            sum(value * value for value in truth))
    return sum(a * b for a, b in zip(learned, truth)) / denominator if denominator else 0.0


def _reason_for_dislike(outfit: SyntheticOutfit, preference: dict[str, float]) -> list[str]:
    negative = [(preference.get(key, 0.0) * value, key)
                for key, value in outfit.features.items() if preference.get(key, 0.0) < 0]
    if not negative:
        return ["pieces_do_not_match"]
    key = min(negative)[1]
    if key.startswith(("color:", "pattern:", "color_pair:", "pattern_balance:")):
        return ["color_pattern"]
    if key.startswith("occasion:"):
        return ["occasion_mismatch"]
    if key.startswith("formality:"):
        return ["too_formal"]
    if key.startswith("layering:"):
        return ["layering"]
    return ["style"]


def _feedback_kind(observed_utility: float, rng: random.Random) -> str | None:
    if observed_utility >= 1.0:
        draw = rng.random()
        return "personal" if draw < 0.10 else "wear" if draw < 0.45 else "liked"
    if observed_utility >= 0.30:
        return "liked"
    if observed_utility <= -0.30:
        return "disliked"
    return None


def simulate_run(config: TasteLearningConfig, scenario: Scenario, *, seed: int,
                 steps: int = 120) -> list[dict]:
    rng = random.Random(seed)
    catalog = synthetic_catalog()
    initial = _personalized_persona(seed, seed % len(PERSONAS))
    changed = _personalized_persona(seed + 10_000, (seed + 1) % len(PERSONAS))
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    sources: list[dict] = []
    exposures = {row.identifier: 0 for row in catalog}
    profile = reduce_sources([], now=start, config=config)
    output = []
    for step in range(steps):
        now = start + timedelta(days=step * 3)
        drift_step = steps // 2
        preference = changed if scenario.drift and step >= drift_step else initial
        predicted = {row.identifier: _eligible_score(row, profile, config) for row in catalog}
        ndcg = _ndcg(catalog, predicted, preference)
        # The online product reserves an exploration share. The simulation uses
        # its Bernoulli equivalent across repeated single recommendation events.
        explore = rng.random() < config.exploration_rate
        if explore:
            least_seen = min(exposures.values())
            pool = [row for row in catalog if exposures[row.identifier] == least_seen and
                    predicted[row.identifier] >= 0]
            chosen = rng.choice(pool or catalog)
        else:
            # A small exposure cost approximates list diversification and avoids
            # repeatedly presenting one exact outfit forever.
            chosen = max(catalog, key=lambda row: (predicted[row.identifier] -
                                                    0.08 * exposures[row.identifier],
                                                    -int(row.identifier[1:])))
        exposures[chosen.identifier] += 1
        utilities = [_utility(row, preference) for row in catalog]
        latent = _utility(chosen, preference)
        spread = statistics.pstdev(utilities) or 1.0
        # A click is relative to what this user normally sees. Centering avoids
        # making every outfit positive merely because latent weights are additive.
        observed = (latent - statistics.fmean(utilities)) / spread + rng.gauss(0.0, 0.25)
        kind = _feedback_kind(observed, rng)
        if kind and rng.random() < scenario.feedback_error_rate:
            kind = "disliked" if kind != "disliked" else "liked"
        if kind:
            reasons = []
            if kind == "disliked" and rng.random() < 0.75:
                reasons = _reason_for_dislike(chosen, preference)
            sources.append({
                "id": f"{seed}-{step}", "kind": kind, "created_at": now.isoformat(),
                "feature_snapshot": chosen.snapshot, "reason_codes": reasons,
            })
            profile = reduce_sources(sources, now=now, config=config)
        oracle = max(_utility(row, preference) for row in catalog)
        output.append({
            "step": step + 1,
            "ndcg_at_10": ndcg,
            "alignment": _alignment(profile, preference, config),
            "regret": oracle - latent,
            "positive": int(kind in {"liked", "wear", "personal"}),
            "negative": int(kind == "disliked"),
            "feedback": int(kind is not None),
            "unique_outfits": sum(value > 0 for value in exposures.values()),
            "profile_active": int((profile.get("generation_memory") or {}).get("evidence_threshold_met", False)),
            "post_drift": int(scenario.drift and step >= drift_step),
            "score_spread": max(predicted.values()) - min(predicted.values()),
            "score_saturation_rate": (sum(abs(value) >= config.maximum_personalization_score - 1e-9
                                           for value in predicted.values()) / len(predicted)),
        })
    return output


def _mean(values: Iterable[float]) -> float:
    rows = list(values)
    return statistics.fmean(rows) if rows else 0.0


def _first_sustained(rows: list[dict], key: str, threshold: float, start: int = 0,
                     window: int = 5) -> int | None:
    for index in range(start, len(rows) - window + 1):
        if _mean(row[key] for row in rows[index:index + window]) >= threshold:
            return index + 1
    return None


def summarize_run(rows: list[dict], scenario: Scenario) -> dict:
    final = rows[-10:]
    activation = next((row["step"] for row in rows if row["profile_active"]), None)
    convergence = _first_sustained(rows, "alignment", 0.50)
    drift_start = len(rows) // 2 if scenario.drift else 0
    recovery = _first_sustained(rows, "alignment", 0.50, drift_start) if scenario.drift else None
    return {
        "final_ndcg_at_10": _mean(row["ndcg_at_10"] for row in final),
        "mean_ndcg_at_10": _mean(row["ndcg_at_10"] for row in rows),
        "final_alignment": _mean(row["alignment"] for row in final),
        "mean_regret": _mean(row["regret"] for row in rows),
        "positive_rate": sum(row["positive"] for row in rows) / len(rows),
        "feedback_rate": sum(row["feedback"] for row in rows) / len(rows),
        "unique_outfits": rows[-1]["unique_outfits"],
        "final_saturation_rate": _mean(row["score_saturation_rate"] for row in final),
        "final_score_spread": _mean(row["score_spread"] for row in final),
        "activation_step": activation if activation is not None else len(rows) + 1,
        "alignment_50_step": convergence if convergence is not None else len(rows) + 1,
        "drift_recovery_step": ((recovery - drift_start) if recovery is not None else len(rows) + 1)
                               if scenario.drift else None,
    }


def _aggregate(records: list[dict], keys: list[str]) -> dict:
    result = {}
    for key in keys:
        values = [float(row[key]) for row in records if row.get(key) is not None]
        if not values:
            result[key] = None
            result[key + "_ci95"] = None
            continue
        result[key] = _mean(values)
        result[key + "_ci95"] = (1.96 * statistics.stdev(values) / math.sqrt(len(values))
                                  if len(values) > 1 else 0.0)
    return result


METRIC_KEYS = ["final_ndcg_at_10", "mean_ndcg_at_10", "final_alignment", "mean_regret",
               "positive_rate", "feedback_rate", "unique_outfits", "activation_step",
               "final_saturation_rate", "final_score_spread", "alignment_50_step",
               "drift_recovery_step"]


def run_experiment(*, runs: int, steps: int,
                   variants: dict[str, TasteLearningConfig] | None = None) -> tuple[list[dict], list[dict], dict]:
    summaries = []
    curve_buckets: dict[tuple[str, str, int], list[dict]] = {}
    variants = variants or parameter_variants()
    for variant_name, config in variants.items():
        for scenario in SCENARIOS:
            for seed in range(runs):
                rows = simulate_run(config, scenario, seed=seed, steps=steps)
                summary = summarize_run(rows, scenario)
                summaries.append({"variant": variant_name, "scenario": scenario.name,
                                  "seed": seed, **summary})
                for row in rows:
                    curve_buckets.setdefault((variant_name, scenario.name, row["step"]), []).append(row)
    grouped = []
    for variant_name in variants:
        for scenario in SCENARIOS:
            records = [row for row in summaries if row["variant"] == variant_name and
                       row["scenario"] == scenario.name]
            grouped.append({"variant": variant_name, "scenario": scenario.name,
                            "runs": len(records), **_aggregate(records, METRIC_KEYS)})
    curves = []
    for (variant, scenario, step), rows in sorted(curve_buckets.items()):
        curves.append({"variant": variant, "scenario": scenario, "step": step,
                       "ndcg_at_10": _mean(row["ndcg_at_10"] for row in rows),
                       "alignment": _mean(row["alignment"] for row in rows),
                       "regret": _mean(row["regret"] for row in rows),
                       "profile_active_rate": _mean(row["profile_active"] for row in rows)})
    metadata = {"runs_per_variant_scenario": runs, "steps_per_run": steps,
                "feedback_interval_days": 3, "scenarios": [asdict(row) for row in SCENARIOS],
                "variants": {name: asdict(config) for name, config in variants.items()},
                "seed_range": [0, runs - 1]}
    return grouped, curves, metadata


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _svg_chart(path: Path, curves: list[dict], scenario: str) -> None:
    allowed = {"default", "custom", "scale_1", "scale_2", "evidence_2", "evidence_5"}
    selected = [row for row in curves if row["scenario"] == scenario and
                row["variant"] in allowed]
    width, height = 1000, 620
    left, top, plot_width, plot_height = 85, 50, 850, 480
    colors = {"default": "#1463ff", "custom": "#059669", "scale_1": "#059669",
              "scale_2": "#7c3aed", "evidence_2": "#ef4444", "evidence_5": "#f59e0b"}
    variants = [name for name in colors if any(row["variant"] == name for row in selected)]
    max_step = max(row["step"] for row in selected)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="20">Taste learning: {scenario} · NDCG@10</text>']
    for tick in range(6):
        value = tick / 5
        y = top + plot_height * (1 - value)
        lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_width}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        lines.append(f'<text x="{left-12}" y="{y+5:.1f}" text-anchor="end" font-family="sans-serif" font-size="13">{value:.1f}</text>')
    for index, variant in enumerate(variants):
        rows = [row for row in selected if row["variant"] == variant]
        points = " ".join(f'{left + plot_width*(row["step"]-1)/max(1,max_step-1):.1f},'
                          f'{top + plot_height*(1-row["ndcg_at_10"]):.1f}' for row in rows)
        lines.append(f'<polyline points="{points}" fill="none" stroke="{colors[variant]}" stroke-width="3"/>')
        x, y = left + index * 170, top + plot_height + 55
        lines.append(f'<line x1="{x}" y1="{y}" x2="{x+25}" y2="{y}" stroke="{colors[variant]}" stroke-width="4"/>')
        lines.append(f'<text x="{x+32}" y="{y+5}" font-family="sans-serif" font-size="13">{variant}</text>')
    lines.extend([f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_height}" stroke="#111827"/>',
                  f'<line x1="{left}" y1="{top+plot_height}" x2="{left+plot_width}" y2="{top+plot_height}" stroke="#111827"/>',
                  f'<text x="{left+plot_width/2}" y="{height-18}" text-anchor="middle" font-family="sans-serif" font-size="14">Feedback opportunities</text>',
                  '</svg>'])
    path.write_text("\n".join(lines))


def _report(grouped: list[dict], metadata: dict) -> str:
    stable = {row["variant"]: row for row in grouped if row["scenario"] == "stable"}
    noisy = {row["variant"]: row for row in grouped if row["scenario"] == "noisy_feedback"}
    drift = {row["variant"]: row for row in grouped if row["scenario"] == "preference_drift"}
    best = max(stable, key=lambda name: (stable[name]["mean_ndcg_at_10"],
                                         -stable[name]["mean_regret"]))
    default = stable["default"]
    rows = [
        "# Taste Profile Default-Value Simulation",
        "",
        "## Scope",
        "",
        f"This deterministic experiment ran {metadata['runs_per_variant_scenario']} synthetic users per parameter variant and scenario for {metadata['steps_per_run']} feedback opportunities. It invokes the production reducer, performs no database writes, and makes no model calls.",
        "",
        "The simulation tests reducer mechanics under known latent preferences. It cannot establish real user satisfaction or justify shipping a parameter change without replaying real feedback and running an online experiment.",
        "",
        "## Primary comparison",
        "",
        "| Variant | Stable mean NDCG@10 | Noisy final NDCG@10 | Final alignment | Saturation | Mean regret | Activation step |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in stable:
        rows.append(f"| {name} | {stable[name]['mean_ndcg_at_10']:.3f} | "
                    f"{noisy[name]['final_ndcg_at_10']:.3f} | "
                    f"{stable[name]['final_alignment']:.3f} | "
                    f"{stable[name]['final_saturation_rate']:.1%} | "
                    f"{stable[name]['mean_regret']:.3f} | "
                    f"{stable[name]['activation_step']:.1f} |")
    rows.extend([
        "", "## Reading the result", "",
        f"The strongest synthetic stable-scenario NDCG variant was `{best}`. The production default reached mean NDCG@10 `{default['mean_ndcg_at_10']:.3f}` and activated after `{default['activation_step']:.1f}` feedback opportunities on average.",
        f"Its final candidate-score saturation rate was `{default['final_saturation_rate']:.1%}`. High saturation means distinct outfits receive the same capped personalization score and the learned profile loses ranking resolution.",
        "",
        "Use the 95% confidence intervals in `summary.csv` when comparing close results. Prefer a parameter only if it improves learning speed without materially worsening noisy-feedback robustness, drift recovery, regret, or catalog coverage.",
        "",
        "## Required follow-up before changing production defaults", "",
        "1. Replay anonymized real feedback snapshots against the same parameter variants.",
        "2. Confirm that offline gains hold separately for cold-start, sparse-feedback, and high-feedback users.",
        "3. Pre-register an online metric and guardrails, then A/B test one change at a time.",
        "4. Keep hard outfit compatibility rules outside the learned preference score.",
        "",
        "## Reproduction", "",
        "```bash",
        "cd backend",
        "python -m tools.evaluation.taste_learning_simulation --runs 100 --steps 120 --output ../evaluation/taste/simulation",
        "```",
    ])
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=100, help="Synthetic users per variant/scenario")
    parser.add_argument("--steps", type=int, default=120, help="Feedback opportunities per user")
    parser.add_argument("--output", type=Path, default=evaluation_path("taste", "simulation"))
    parser.add_argument("--custom-config", type=Path,
                        help="JSON overrides compared with the unchanged production default")
    args = parser.parse_args()
    if args.runs < 2 or args.steps < 20:
        parser.error("--runs must be at least 2 and --steps at least 20")
    args.output.mkdir(parents=True, exist_ok=True)
    variants = None
    if args.custom_config:
        overrides = json.loads(args.custom_config.read_text())
        known = set(asdict(DEFAULT_TASTE_LEARNING_CONFIG))
        unknown = set(overrides) - known
        if unknown:
            parser.error(f"Unknown custom parameters: {', '.join(sorted(unknown))}")
        values = {**asdict(DEFAULT_TASTE_LEARNING_CONFIG), **overrides}
        variants = {"default": DEFAULT_TASTE_LEARNING_CONFIG,
                    "custom": TasteLearningConfig(**values)}
    grouped, curves, metadata = run_experiment(runs=args.runs, steps=args.steps, variants=variants)
    _write_csv(args.output / "summary.csv", grouped)
    _write_csv(args.output / "learning_curves.csv", curves)
    (args.output / "config.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))
    (args.output / "report.md").write_text(_report(grouped, metadata))
    for scenario in ("stable", "noisy_feedback", "preference_drift"):
        _svg_chart(args.output / f"{scenario}_learning_curve.svg", curves, scenario)
    print(json.dumps({"output": str(args.output.resolve()), "variants": len(variants or parameter_variants()),
                      "scenarios": len(SCENARIOS), "runs": args.runs, "steps": args.steps}, indent=2))


if __name__ == "__main__":
    main()
