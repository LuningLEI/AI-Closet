from app.models.domain import ClothingItemRecord
from app.outfits.catalog import select_catalog,exclusion_reason,cosine
from app.outfits.config import load_config


def item(category,subtype=None,**kw):
    return ClothingItemRecord(user_id='u',image_url='',category=category,subtype=subtype,**kw)


def test_top_keeps_skirts_but_excludes_dresses_and_duplicate_shirts():
    anchor=item('Tops','Blouse',semantic_vector=[1,0])
    skirt=item('Bottoms','Pencil Skirt',semantic_vector=[0,1])
    pants=item('Bottoms','Trousers')
    dress=item('Dresses','Midi Dress',semantic_vector=[1,0])
    shirt=item('Tops','Blouse',semantic_vector=[1,0])
    result=select_catalog(anchor,[anchor,dress,skirt,pants,shirt],load_config())
    assert {i.id for i in result}=={anchor.id,skirt.id,pants.id}


def test_vector_orders_compatible_items_not_forbidden_ones():
    anchor=item('Tops','Blouse',semantic_vector=[1,0])
    near=item('Bottoms','Trousers',semantic_vector=[1,0])
    far=item('Bottoms','Trousers',semantic_vector=[0,1])
    assert select_catalog(anchor,[anchor,far,near],load_config())[1].id==near.id
    conflict=item('Bottoms','Shorts',style='Sporty',semantic_vector=[1,0])
    anchor.style='Business'
    assert exclusion_reason(anchor,conflict,load_config())=='explicit_style_conflict'


def test_thermal_and_vector_fallback_do_not_need_model_or_images():
    anchor=item('Outerwear','Puffer',warmth_level=5)
    shorts=item('Bottoms','Shorts',warmth_level=1)
    pants=item('Bottoms','Trousers',warmth_level=3)
    assert exclusion_reason(anchor,shorts,load_config())
    assert pants.id in {i.id for i in select_catalog(anchor,[anchor,shorts,pants],load_config())}
    assert cosine([1,2],[1]) is None
    assert cosine([0,0],[1,0]) is None
    assert cosine([float('nan')],[1]) is None


def test_disjoint_season_and_warmth_are_excluded_before_generation():
    anchor=item('Outerwear','Jacket',season='Fall, Winter',warmth_level=4)
    summer=item('Jumpsuits','Jumpsuit',season='Summer',warmth_level=1)
    fall=item('Dresses','Sweater Dress',season='Fall, Winter',warmth_level=4)
    assert exclusion_reason(anchor,summer,load_config())=='Items have no shared season and materially conflicting warmth levels.'
    selected={i.id for i in select_catalog(anchor,[anchor,summer,fall],load_config())}
    assert summer.id not in selected and fall.id in selected


def test_catalog_limit_and_layering_and_owner_safety():
    config=load_config().model_copy(update={'catalog_limit':2})
    anchor=item('Outerwear','Jacket')
    candidates=[item('Tops','Blouse') for _ in range(5)]+[item('Bottoms','Trousers') for _ in range(5)]
    assert len(select_catalog(anchor,[anchor]+candidates,config))==2
    top=item('Tops','Tank Top');vest=item('Tops','Vest')
    assert exclusion_reason(top,vest,config) is None
    foreign=vest.model_copy(update={'user_id':'other'})
    assert exclusion_reason(top,foreign,config)=='different_owner'


def test_catalog_changes_version_generation_without_invalidating_visual_reviews():
    config=load_config()
    changed=config.model_copy(update={'catalog_rules':config.catalog_rules.model_copy(update={'metadata_weight':1})})
    assert config.generation_key!=changed.generation_key
    assert config.evaluator_key==changed.evaluator_key


def test_generation_reads_vectors_while_frontend_item_reads_stay_small(repository,tmp_path):
    from app.outfits.service import OutfitLibrary
    from app.outfits.store import LocalOutfitStore
    top=item('Tops','Blouse',semantic_vector=[1,0],feature_vector=[1]*13)
    repository.add_item(top)
    lib=OutfitLibrary(repository,LocalOutfitStore(tmp_path/'outfits.sqlite3'),load_config())
    assert lib.items('u',include_vectors=True)[top.id].semantic_vector==[1,0]
    assert lib.items('u')[top.id].semantic_vector is None
