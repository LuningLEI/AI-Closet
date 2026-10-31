import pytest
from tools.evaluation.analyze_human_eval import occasion_hit_metrics, write_metrics, HUMAN_AGREEMENT_METHOD
import csv


def test_occasion_hit_accepts_any_position_without_penalizing_extras():
    metrics = occasion_hit_metrics(['Work', 'Date', 'Everyday'], ['Everyday, Work', 'Travel, Work', 'Everyday, Date'])
    assert metrics['hits'] == 2
    assert metrics['hit_rate'] == pytest.approx(2/3)
    assert metrics['mean_prediction_count'] == 2
    assert 'macro_f1' not in metrics


def test_empty_prediction_misses_and_invalid_taxonomy_is_rejected():
    assert occasion_hit_metrics(['Work'], [''])['hits'] == 0
    assert occasion_hit_metrics([], [])['hit_rate'] is None
    with pytest.raises(ValueError):
        occasion_hit_metrics(['Work'], ['Unknown'])


def test_majority_exclusions_and_current_model_name(tmp_path):
    path = tmp_path / 'metrics.csv'
    write_metrics(path, {'occasion': [
        ['Work', 'Work', 'Date', 'Date, Work', 'Everyday, Work'],
        ['Work', 'Date', 'Everyday', 'Date', 'Everyday'],
        ['Date', 'Date', 'Work', '', 'Date'],
    ]}, {}, {'occasion': ['Human 1', 'Human 2', 'Human 3', 'baseline-picture', 'current-recognition-model']})
    rows = list(csv.DictReader(path.open()))
    machines = [r for r in rows if 'vs human-majority' in r['method']]
    assert len(machines) == 2
    assert all(r['n'] == '1' and r['hit_rate'] == '1.000' and r['macro_f1'] == '' for r in machines)
    assert machines[1]['method'] == 'current-recognition-model vs human-majority'
    assert machines[1]['excluded_no_majority'] == '1'
    assert machines[1]['excluded_missing_prediction'] == '1'
    assert next(r for r in rows if r['method'] == HUMAN_AGREEMENT_METHOD)['n'] == '3'
