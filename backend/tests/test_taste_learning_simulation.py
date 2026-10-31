from app.services.taste_profile import DEFAULT_TASTE_LEARNING_CONFIG
from tools.evaluation.taste_learning_simulation import SCENARIOS, simulate_run, summarize_run


def test_simulation_is_deterministic_and_reports_learning_metrics():
    first = simulate_run(DEFAULT_TASTE_LEARNING_CONFIG, SCENARIOS[0], seed=7, steps=24)
    second = simulate_run(DEFAULT_TASTE_LEARNING_CONFIG, SCENARIOS[0], seed=7, steps=24)
    assert first == second
    summary = summarize_run(first, SCENARIOS[0])
    assert len(first) == 24
    assert 0 <= summary["final_ndcg_at_10"] <= 1
    assert summary["mean_regret"] >= 0
    assert summary["unique_outfits"] > 1
