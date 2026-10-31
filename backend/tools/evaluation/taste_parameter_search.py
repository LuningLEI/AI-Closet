"""Two-stage deterministic search for Taste Profile simulation defaults."""
from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import asdict, replace
from pathlib import Path

from app.services.taste_profile import DEFAULT_TASTE_LEARNING_CONFIG, TasteLearningConfig
from tools.evaluation.taste_learning_simulation import run_experiment
from tools.evaluation.paths import evaluation_path


SEARCH_SEED = 20261029


def candidate_configs(count: int) -> dict[str, TasteLearningConfig]:
    default = DEFAULT_TASTE_LEARNING_CONFIG
    rng = random.Random(SEARCH_SEED)
    spaces = {
        "personalization_scale": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
        "generation_evidence_threshold": [2, 3, 4, 5],
        "exploration_rate": [0.05, 0.10, 0.15, 0.20],
        "half_life_days": [90.0, 120.0, 180.0, 270.0, 365.0],
        "prior_strength": [2.5, 5.0, 7.5, 10.0],
        "decay_floor": [0.0, 0.15, 0.30, 0.45],
        "signal_multiplier": [0.75, 1.0, 1.25, 1.5],
    }
    variants = {"default": default}
    seen = set()
    while len(variants) < count + 1:
        choice = tuple(rng.choice(spaces[key]) for key in spaces)
        if choice in seen:
            continue
        seen.add(choice)
        scale, threshold, exploration, half_life, prior, floor, multiplier = choice
        config = replace(
            default,
            personalization_scale=scale,
            generation_evidence_threshold=threshold,
            exploration_rate=exploration,
            half_life_days=half_life,
            prior_strength=prior,
            decay_floor=floor,
            personal_strength=default.personal_strength * multiplier,
            wear_strength=default.wear_strength * multiplier,
            liked_strength=default.liked_strength * multiplier,
            disliked_strength=default.disliked_strength * multiplier,
        )
        variants[f"candidate_{len(variants):03d}"] = config
    return variants


def _normalize(values: dict[str, float], *, lower_is_better: bool = False) -> dict[str, float]:
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {key: 1.0 for key in values}
    normalized = {key: (value - low) / (high - low) for key, value in values.items()}
    return {key: 1.0 - value for key, value in normalized.items()} if lower_is_better else normalized


def score_variants(grouped: list[dict]) -> list[dict]:
    names = sorted({row["variant"] for row in grouped})
    lookup = {(row["variant"], row["scenario"]): row for row in grouped}
    specs = [
        ("stable_mean_ndcg", 0.25, False,
         lambda name: lookup[name, "stable"]["mean_ndcg_at_10"]),
        ("noisy_mean_ndcg", 0.15, False,
         lambda name: lookup[name, "noisy_feedback"]["mean_ndcg_at_10"]),
        ("drift_mean_ndcg", 0.15, False,
         lambda name: lookup[name, "preference_drift"]["mean_ndcg_at_10"]),
        ("stable_regret", 0.15, True,
         lambda name: lookup[name, "stable"]["mean_regret"]),
        ("drift_recovery", 0.10, True,
         lambda name: lookup[name, "preference_drift"]["drift_recovery_step"]),
        ("saturation", 0.10, True,
         lambda name: lookup[name, "stable"]["final_saturation_rate"]),
        ("coverage", 0.05, False,
         lambda name: lookup[name, "stable"]["unique_outfits"]),
        ("activation", 0.05, True,
         lambda name: lookup[name, "stable"]["activation_step"]),
    ]
    output = {name: {"variant": name, "selection_score": 0.0} for name in names}
    for label, weight, lower, getter in specs:
        raw = {name: float(getter(name)) for name in names}
        normalized = _normalize(raw, lower_is_better=lower)
        for name in names:
            output[name][label] = raw[name]
            output[name][label + "_normalized"] = normalized[name]
            output[name]["selection_score"] += weight * normalized[name]
    return sorted(output.values(), key=lambda row: (-row["selection_score"], row["variant"]))


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _comparison(grouped: list[dict], winner: str) -> list[dict]:
    return [row for row in grouped if row["variant"] in {"default", winner}]


def _report(winner: str, config: TasteLearningConfig, ranked: list[dict], grouped: list[dict],
            args) -> str:
    lookup = {(row["variant"], row["scenario"]): row for row in grouped}
    rows = [
        "# Taste 参数搜索结果",
        "",
        f"推荐候选：`{winner}`。这是在 synthetic simulation 的预设综合目标下排名第一的配置，不会自动写入生产环境。",
        "",
        "## 推荐参数",
        "",
        "```json",
        json.dumps(asdict(config), indent=2, sort_keys=True),
        "```",
        "",
        "## 与当前默认值比较",
        "",
        "| 场景 | 配置 | Mean NDCG@10 | Mean regret ↓ | Final alignment | Saturation ↓ | Activation | Drift recovery ↓ |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in ("stable", "noisy_feedback", "preference_drift"):
        for name in ("default", winner):
            row = lookup[name, scenario]
            recovery = row["drift_recovery_step"]
            rows.append(f"| {scenario} | {name} | {row['mean_ndcg_at_10']:.3f} | "
                        f"{row['mean_regret']:.3f} | {row['final_alignment']:.3f} | "
                        f"{row['final_saturation_rate']:.1%} | {row['activation_step']:.1f} | "
                        f"{recovery:.1f} |" if recovery is not None else
                        f"| {scenario} | {name} | {row['mean_ndcg_at_10']:.3f} | "
                        f"{row['mean_regret']:.3f} | {row['final_alignment']:.3f} | "
                        f"{row['final_saturation_rate']:.1%} | {row['activation_step']:.1f} | — |")
    rows.extend([
        "", "## 选择方法", "",
        "综合分数预先固定为：稳定 NDCG 25%、噪声 NDCG 15%、偏好变化 NDCG 15%、稳定 regret 15%、偏好变化恢复 10%、分数饱和 10%、覆盖率 5%、冷启动速度 5%。所有参数使用相同随机种子，进行 paired comparison。",
        "",
        f"第一阶段：{args.candidates} 个候选，每组 {args.search_runs} 个虚拟用户、{args.search_steps} 次反馈。",
        f"第二阶段：前 {args.finalists} 名加当前默认值，每组 {args.validation_runs} 个虚拟用户、{args.validation_steps} 次反馈。",
        "",
        "## 使用边界", "",
        "这是当前模拟假设下的最优候选，不等于真实用户全局最优。下一步应使用真实匿名反馈 replay 验证推荐候选，再决定是否改生产默认值。",
        "",
        "完整排名见 `validation_ranking.csv`，第一阶段结果见 `search_ranking.csv`。",
    ])
    return "\n".join(rows) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=int, default=48)
    parser.add_argument("--search-runs", type=int, default=10)
    parser.add_argument("--search-steps", type=int, default=90)
    parser.add_argument("--finalists", type=int, default=6)
    parser.add_argument("--validation-runs", type=int, default=30)
    parser.add_argument("--validation-steps", type=int, default=120)
    parser.add_argument("--output", type=Path,
                        default=evaluation_path("taste", "parameter_search"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    candidates = candidate_configs(args.candidates)
    search_grouped, _, search_meta = run_experiment(
        runs=args.search_runs, steps=args.search_steps, variants=candidates)
    search_ranking = score_variants(search_grouped)
    finalist_names = [row["variant"] for row in search_ranking[:args.finalists]]
    if "default" not in finalist_names:
        finalist_names.append("default")
    finalists = {name: candidates[name] for name in finalist_names}

    validation_grouped, validation_curves, validation_meta = run_experiment(
        runs=args.validation_runs, steps=args.validation_steps, variants=finalists)
    validation_ranking = score_variants(validation_grouped)
    winner = next(row["variant"] for row in validation_ranking if row["variant"] != "default")

    _write_csv(args.output / "search_ranking.csv", search_ranking)
    _write_csv(args.output / "validation_ranking.csv", validation_ranking)
    _write_csv(args.output / "validation_summary.csv", validation_grouped)
    _write_csv(args.output / "validation_learning_curves.csv", validation_curves)
    (args.output / "search_space.json").write_text(json.dumps(
        {name: asdict(config) for name, config in candidates.items()}, indent=2, sort_keys=True))
    (args.output / "experiment.json").write_text(json.dumps(
        {"search": search_meta, "validation": validation_meta,
         "selection_weights": {"stable_ndcg": .25, "noisy_ndcg": .15,
                               "drift_ndcg": .15, "regret": .15,
                               "drift_recovery": .10, "saturation": .10,
                               "coverage": .05, "activation": .05}}, indent=2, sort_keys=True))
    (args.output / "recommended_config.json").write_text(
        json.dumps(asdict(finalists[winner]), indent=2, sort_keys=True))
    (args.output / "report.zh-CN.md").write_text(
        _report(winner, finalists[winner], validation_ranking, validation_grouped, args))
    print(json.dumps({"winner": winner, "output": str(args.output.resolve()),
                      "search_candidates": len(candidates), "validated": len(finalists)}, indent=2))


if __name__ == "__main__":
    main()
