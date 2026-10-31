import math

import pytest

from app.models.api import ClothingItemUpdateRequest
from app.models.domain import ClothingItemRecord
from app.services.item_service import ItemService
from app.services.recognition_service import ClothingRecognitionService


def analyze(scores, threshold=0.5):
    return ClothingRecognitionService(occasion_threshold=threshold)._normalize_model_payload(
        {"occasion_scores": scores}, raw_response={}
    )


def test_multilabel_sorted_inclusive_threshold_and_retained_low_scores():
    result = analyze([
        {"occasion": "Travel", "score": 0.3},
        {"occasion": "Work", "score": 0.5},
        {"occasion": "Everyday", "score": 0.9},
    ])
    assert result.occasion == "Everyday, Work"
    assert [s.score for s in result.occasion_scores] == [0.9, 0.5, 0.3]
    assert result.occasion_threshold == 0.5
    assert analyze([s.model_dump() for s in result.occasion_scores], 0.95).occasion == "Everyday"
    assert analyze([s.model_dump() for s in result.occasion_scores], 0).occasion == "Everyday, Work, Travel"


def test_invalid_labels_and_scores_are_not_mapped_to_everyday():
    result = analyze([
        {"occasion": " work ", "score": 0.7},
        {"occasion": "Work", "score": 0.9},
        {"occasion": "Invented", "score": 1},
        {"occasion": "Everyday", "score": True},
        {"occasion": "Party", "score": math.nan},
        {"occasion": "Date", "score": math.inf},
        {"occasion": "Travel", "score": 1.2},
        {"occasion": "Evening", "score": -0.2},
        None,
    ])
    assert result.occasion == "Work"
    assert len(result.occasion_scores) == 1
    assert result.occasion_scores[0].score == 0.9


def test_legacy_response_does_not_invent_scores():
    result = ClothingRecognitionService()._normalize_model_payload({"occasion": "office"}, {})
    assert result.occasion == "Work"
    assert result.occasion_scores == []
    assert result.occasion_threshold is None


@pytest.mark.parametrize("threshold", [-0.1, 1.1, math.nan, math.inf])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        ClothingRecognitionService(occasion_threshold=threshold)


def test_manual_selection_preserves_prediction_for_later_threshold_testing(repository):
    class NoEmbedding:
        def create_embedding(self, text):
            return None

    prediction = analyze([{"occasion": "Work", "score": 0.8}])
    item = repository.add_item(ClothingItemRecord(
        user_id="tester", image_url="https://example.test/item.jpg", category="Tops",
        occasion=prediction.occasion, recognition_tags=prediction.model_dump(),
    ))
    updated = ItemService(repository, NoEmbedding()).update_item("tester", item.id, ClothingItemUpdateRequest(
        category="Tops", color="White", season="Summer", style="Casual", occasion="", edit_source="ios",
    ))
    assert updated.occasion == ""
    assert updated.recognition_tags["occasion_scores"] == [{"occasion": "Work", "score": 0.8}]
    assert updated.recognition_tags["occasion_threshold"] == 0.5


def test_current_threshold_changes_display_and_recommendation_without_mutating_scores(monkeypatch):
    from types import SimpleNamespace
    from app.services.occasion_support import occasion_for_display
    from app.services.recommendation.rules import item_occasion_tokens
    from app.services.recommendation.candidates import CandidateGenerator

    item = ClothingItemRecord(user_id='test', image_url='https://example.test/a.jpg', category='Tops',
        occasion='Work, Travel', recognition_tags={'occasion_threshold': 0.5, 'occasion_scores': [
            {'occasion':'Work','score':0.8}, {'occasion':'Travel','score':0.7}, {'occasion':'Everyday','score':0.1},
        ]})
    original = item.model_dump()
    monkeypatch.setattr('app.services.occasion_support.settings', SimpleNamespace(recognition_occasion_threshold=0.8))
    display = occasion_for_display(item)
    assert display.occasion == 'Work'
    assert display.recognition_tags['display_occasion_threshold'] == 0.8
    assert display.recognition_tags['occasion_threshold'] == 0.5
    assert item_occasion_tokens(item) == {'work'}
    from app.services.recommendation.scorer import CandidateScorer
    from app.services.recommendation.models import Candidate
    from app.models.domain import RecommendationContext
    from app.services.response_signing import ResponseSigningService
    class Storage:
        def signed_image_url(self, path): return None
        def fallback_image_url(self, path): return None
    response = ResponseSigningService(Storage()).item(item, 'https://example.test')
    assert response.occasion == 'Work'
    assert response.recognition_tags['occasion_scores'] == original['recognition_tags']['occasion_scores']
    scorer = CandidateScorer(object())
    candidate, context = Candidate(top=item), RecommendationContext(occasion='Travel')
    strict_fit = scorer._occasion_score(candidate, context)[0]
    generator = CandidateGenerator()
    strict_score = generator._occasion_score(item, 'Travel')
    monkeypatch.setattr('app.services.occasion_support.settings', SimpleNamespace(recognition_occasion_threshold=0.7))
    assert occasion_for_display(item).occasion == 'Work, Travel'
    assert generator._occasion_score(item, 'Travel') > strict_score
    assert scorer._occasion_score(candidate, context)[0] > strict_fit
    assert item.model_dump() == original
    assert display.recognition_tags['occasion_scores'] == original['recognition_tags']['occasion_scores']


def test_no_threshold_matches_selects_highest_and_manual_selection_wins(monkeypatch):
    from types import SimpleNamespace
    from app.services.occasion_support import occasion_for_display
    from app.services.recommendation.rules import item_occasion_tokens
    monkeypatch.setattr('app.services.occasion_support.settings', SimpleNamespace(recognition_occasion_threshold=0.8))
    item = ClothingItemRecord(user_id='test', image_url='https://example.test/a.jpg', category='Tops',
        occasion='Everyday', recognition_tags={'occasion_scores':[{'occasion':'Everyday','score':0.7}]})
    assert occasion_for_display(item).occasion == 'Everyday'
    assert item_occasion_tokens(item) == {'everyday'}
    item.recognition_status = 'manual'
    item.occasion = 'Party, Date'
    assert item_occasion_tokens(item) == {'party','date'}
    assert occasion_for_display(item).occasion == 'Party, Date'


@pytest.mark.parametrize('scores, expected', [
    ([{'occasion':'Date','score':0.7},{'occasion':'Everyday','score':0.6}], 'Date'),
    ([{'occasion':'Date','score':0.7},{'occasion':'Everyday','score':0.7}], 'Everyday'),
    ([{'occasion':'Date','score':0.0},{'occasion':'Everyday','score':0.0}], 'Everyday'),
    ([{'occasion':'Date','score':0.8},{'occasion':'Everyday','score':0.9}], 'Everyday, Date'),
])
def test_recognition_and_existing_item_fallback_agree_without_losing_scores(monkeypatch, scores, expected):
    from types import SimpleNamespace
    from app.services.occasion_support import occasion_for_display
    from app.services.recommendation.rules import item_occasion_tokens
    monkeypatch.setattr('app.services.occasion_support.settings', SimpleNamespace(recognition_occasion_threshold=0.8))
    prediction = analyze(scores, 0.8)
    assert prediction.occasion == expected
    item = ClothingItemRecord(user_id='test', image_url='https://example.test/a.jpg', category='Tops',
                              occasion='', recognition_tags={'occasion_scores':scores})
    before = item.model_dump()
    assert occasion_for_display(item).occasion == expected
    assert item_occasion_tokens(item) == {label.lower() for label in expected.split(', ')}
    assert item.model_dump() == before
    assert len(prediction.occasion_scores) == len(scores)
