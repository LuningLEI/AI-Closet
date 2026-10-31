from app.models.domain import ClothingItemRecord
from app.outfits.compatibility import compatibility_issues


def item(category,subtype,**kwargs):
    return ClothingItemRecord(user_id='u',category=category,subtype=subtype,image_url='https://example.test/photo',**kwargs)


def test_patterns_and_deliberate_solid_contrasts():
    for colors in [('Pink','Pink'),('Black','White'),('Green','Brown'),('Blue','Yellow')]:
        assert not compatibility_issues([item('Tops','Blouse',color=colors[0],pattern='Solid'),item('Bottoms','Trousers',color=colors[1],pattern='Solid')])
    assert compatibility_issues([item('Tops','Blouse',pattern='Floral'),item('Bottoms','Shorts',pattern='Gingham')])
    assert not compatibility_issues([item('Tops','Blouse',pattern='Floral'),item('Bottoms','Shorts',pattern='Solid')])
    assert not compatibility_issues([item('Tops','Mesh Top',pattern='Mesh'),item('Bottoms','Trousers',pattern='Solid')])


def test_short_bottoms_cannot_have_puffer_options():
    for category,subtype in [('Bottoms','Mini Skirt'),('Bottoms','Shorts'),('Activewear','Athletic Skirt')]:
        assert compatibility_issues([item(category,subtype),item('Outerwear','Puffer')])
    assert not compatibility_issues([item('Bottoms','Trousers'),item('Outerwear','Puffer')])
    assert not compatibility_issues([item('Bottoms','Mini Skirt'),item('Outerwear','Jacket')])


def test_white_shirt_denim_shorts_and_pencil_skirt_are_allowed():
    shirt = item('Tops', 'Blouse', color='White', pattern='Solid',
                 style='Business', formality_score=4, occasion='Work', warmth_level=1)
    for bottom in [item('Bottoms', 'Shorts', color='Blue', material='Denim',
                        occasion='Vacation', formality_score=1, warmth_level=1),
                   item('Bottoms', 'Pencil Skirt', color='Black', occasion='Work')]:
        assert not compatibility_issues([shirt, bottom])
    assert not compatibility_issues([shirt.model_copy(update={'color':'Pink'}),
                                    item('Bottoms','Pencil Skirt',color='Black')])


def test_purpose_conflicts_require_concrete_evidence():
    assert compatibility_issues([item('Activewear','Workout Top'), item('Bottoms','Pencil Skirt')])
    assert compatibility_issues([item('Activewear','Ski Jacket'), item('Bottoms','Mini Skirt')])
    assert not compatibility_issues([item('Activewear','Workout Top',color='Pink'),
                                    item('Activewear','Workout Leggings',color='Pink')])
    assert not compatibility_issues([item('Tops','T-shirt'), item('Bottoms','Pencil Skirt')])
    assert not compatibility_issues([item('Tops','Unknown'), item('Bottoms','Unknown')])


def test_thermal_rules_preserve_normal_layers_and_cropped_trousers():
    assert compatibility_issues([item('Tops','Sweater',warmth_level=5),
                                 item('Bottoms','Shorts',warmth_level=1)])
    assert not compatibility_issues([item('Tops','T-shirt',warmth_level=1),
                                    item('Bottoms','Trousers',warmth_level=3),
                                    item('Outerwear','Puffer',warmth_level=5)])
    assert not compatibility_issues([item('Bottoms','Trousers',length='Cropped'),
                                    item('Outerwear','Puffer')])


def test_compatibility_settings_do_not_invalidate_generation():
    from app.outfits.config import load_config
    config = load_config()
    changed = config.model_copy(update={'compatibility_rules':
        config.compatibility_rules.model_copy(update={'block_purpose_conflicts':False})})
    pair = [item('Activewear','Workout Top'), item('Bottoms','Pencil Skirt')]
    assert compatibility_issues(pair, config.compatibility_rules)
    assert not compatibility_issues(pair, changed.compatibility_rules)
    assert config.generation_key == changed.generation_key
    assert config.evaluator_key == changed.evaluator_key


def test_model_receives_garment_context_without_current_weather():
    import json
    from app.outfits.provider import VisionOutfitProvider
    from app.outfits.config import load_config
    class Storage:
        def signed_image_url(self,*args,**kwargs):return 'https://example.test/signed'
    garment=item('Bottoms','Pencil Skirt',pattern='Solid',warmth_level=3,formality_score=4,occasion='Work',season='Fall')
    content=VisionOutfitProvider(load_config(),Storage()).images([garment])
    labels=json.loads(content[0]['text'])
    assert labels['pattern']=='Solid' and labels['warmth_level']==3
    assert labels['formality_score']==4 and labels['occasion']=='Work'
    assert labels['season']=='Fall' and 'temperature' not in labels
