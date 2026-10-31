from app.services.season_support import normalize_seasons, SEASONS
from app.services.taxonomy import SEASONS as OPTIONS
from app.models.domain import ClothingAnalysis
from app.models.api import ClothingItemUpdateRequest
from app.services.recognition_service import ClothingRecognitionService

def test_four_options_and_default():
    assert OPTIONS == ['Spring','Summer','Fall','Winter']
    assert ClothingAnalysis().seasons == OPTIONS

def test_legacy_and_partial_normalization():
    assert normalize_seasons('All-Season, Summer') == SEASONS
    assert normalize_seasons(['Winter','autumn','winter']) == ['Fall','Winter']
    assert normalize_seasons([]) == SEASONS
    assert ClothingRecognitionService()._normalize_seasons(['year-round']) == SEASONS
    assert ClothingAnalysis(seasons=['All-Season']).seasons == SEASONS

def test_edit_accepts_legacy_but_stores_four_seasons():
    data=ClothingItemUpdateRequest(category='Tops',color='Blue',season='All-Season',style='Casual',occasion='Everyday')
    assert data.season == 'Spring, Summer, Fall, Winter'
