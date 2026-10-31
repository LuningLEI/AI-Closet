"""Directional upper/lower-body constraints; capabilities determine valid layers."""
from itertools import permutations
from app.services.recommendation.rules import recommendation_slot, layers_compatible, is_tights, tights_cover


def explicit_layer(inner, outer):
    return inner.wearing_profile['can_layer_under'] is True and outer.wearing_profile['can_layer_over'] is True


def lower_layer_pair(inner, outer):
    a,b=inner.wearing_profile,outer.wearing_profile
    if inner.subtype == 'Yoga Pants' and (inner.fit or '').lower() in {'wide-leg', 'flared'}:
        return False  # Loose yoga trousers are not a leggings-like inner layer.
    if is_tights(inner):
        return tights_cover(outer) and a['can_layer_under'] is not False and b['can_layer_over'] is not False
    return (recommendation_slot(inner.category,inner.subtype)=='Bottoms'
            and recommendation_slot(outer.category,outer.subtype) in {'Bottoms','FullBody'}
            and a['lower_layer_role']=='base' and b['lower_layer_role']=='outer'
            and explicit_layer(inner,outer))


def valid_order(garments, pair_compatible, edge_test=explicit_layer):
    if not garments:return True
    for ordered in permutations(garments):
        edges=[edge_test(a,b) for a,b in zip(ordered,ordered[1:])]
        if any(not pair_compatible(a,b) for a,b in zip(ordered,ordered[1:])):continue
        good=True
        for index,item in enumerate(ordered):
            profile=item.wearing_profile
            inner=index>0 and edges[index-1]
            outer=index<len(edges) and edges[index]
            if profile['requires_inner_layer'] is True and not inner:good=False;break
            if profile['can_wear_alone'] is False and not (inner or outer):good=False;break
        if good:return True
    return False


def valid_layering(items):
    upper=[i for i in items if recommendation_slot(i.category,i.subtype) in {'Tops','Outerwear','FullBody'}]
    bottoms=[i for i in items if recommendation_slot(i.category,i.subtype)=='Bottoms' or is_tights(i)]
    # A dress may cover a lower base only when its lower-layer role is explicit.
    dresses=[i for i in items if recommendation_slot(i.category,i.subtype)=='FullBody'] if bottoms else []
    return valid_order(upper,layers_compatible) and valid_order(bottoms+dresses,lower_layer_pair,lower_layer_pair)
