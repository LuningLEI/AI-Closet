from tools.evaluation.taste_parameter_search import candidate_configs, score_variants


def test_candidate_search_is_deterministic_and_includes_default():
    first = candidate_configs(4)
    second = candidate_configs(4)
    assert first == second
    assert list(first)[0] == "default"
    assert len(first) == 5


def test_selection_score_prefers_balanced_metrics():
    rows = []
    for name, good in [("good", True), ("bad", False)]:
        for scenario in ("stable", "noisy_feedback", "preference_drift"):
            rows.append({"variant": name, "scenario": scenario,
                         "mean_ndcg_at_10": .8 if good else .2,
                         "mean_regret": 1 if good else 4,
                         "drift_recovery_step": 5 if good else 30,
                         "final_saturation_rate": .1 if good else .9,
                         "unique_outfits": 30 if good else 10,
                         "activation_step": 4 if good else 12})
    assert score_variants(rows)[0]["variant"] == "good"
