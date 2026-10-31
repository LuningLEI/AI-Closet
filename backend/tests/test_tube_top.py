from app.services.taxonomy import SUBTYPES, normalize_subtype
from app.services.recommendation.rules import top_layer, layers_compatible
from app.core.constants import LayeringRole
from app.models.domain import ClothingItemRecord


def test_tube_top_normalization_and_existing_types():
    assert 'Tube Top' in SUBTYPES['Tops']
    for name in ['Tube Top','cropped tube top','Strapless Top']:
        assert normalize_subtype('Tops',name)=='Tube Top'
    assert normalize_subtype('Tops','Crop Top') is None
    for name in ['Tank Top','Camisole','Mesh Top']:
        assert normalize_subtype('Tops',name)==name


def test_tube_top_can_layer_under_cardigan():
    top=ClothingItemRecord(user_id='test-user',category='Tops',subtype='Tube Top',recognition_tags={'wearing_profile':{'can_layer_under':True}},image_url='https://example.test/top')
    cardigan=ClothingItemRecord(user_id='test-user',category='Outerwear',subtype='Cardigan',image_url='https://example.test/cardigan')
    assert top_layer(top)==LayeringRole.BASE_TOP
    assert layers_compatible(top,cardigan)
