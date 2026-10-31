"""No image reads or API calls: exclude incompatible roles, then rank vectors."""
from app.services.layering_support import lower_layer_pair
from app.services.recommendation.rules import is_tights
import math
from collections import defaultdict
from app.outfits.compatibility import slot, compatibility_issues, accessory_role, pair_priority
from app.outfits.config import digest
from app.services.recommendation.rules import layers_compatible
from app.services.taste_profile import item_taste_score


def cosine(a,b):
    if not a or not b or len(a)!=len(b):return None
    if not all(math.isfinite(v) for v in [*a,*b]):return None
    na=math.sqrt(sum(v*v for v in a));nb=math.sqrt(sum(v*v for v in b))
    if not na or not nb:return None
    return max(-1.,min(1.,sum(x*y for x,y in zip(a,b))/na/nb))


def metadata_vector(item):
    # Same coordinate names for all items. Avoid rewarding same garment category
    # or penalizing complementary colors. Missing labels carry no evidence.
    values={}
    for field in ['style','season','occasion']:
        for token in (getattr(item,field) or '').lower().split(','):
            token=token.strip()
            if token and token not in {'unknown','none'}:values[field+':'+token]=1.
    for field in ['warmth_level','formality_score']:
        value=getattr(item,field)
        if value is not None:
            for level in range(1,6):values[f'{field}:{level}']=max(0.,1-abs(value-level)/2)
    return values


def metadata_similarity(a,b):
    av,bv=metadata_vector(a),metadata_vector(b);keys=sorted(av.keys()|bv.keys())
    return cosine([av.get(k,0.) for k in keys],[bv.get(k,0.) for k in keys]) or 0.


def exclusion_reason(anchor,item,config):
    a,b=slot(anchor),slot(item)
    if item.user_id!=anchor.user_id:return 'different_owner'
    for hosiery,other in [(anchor,item),(item,anchor)]:
        if is_tights(hosiery) and slot(other) in {'Bottoms','FullBody'} and not lower_layer_pair(hosiery,other):
            return 'tights_need_skirt_shorts_or_dress_not_trousers'
    lower_pair=lower_layer_pair(anchor,item) or lower_layer_pair(item,anchor)
    if a in {'Tops','Bottoms'} and b=='FullBody' and not lower_pair:return 'one_piece_does_not_complement_separates'
    if a=='FullBody' and b in {'Tops','Bottoms','FullBody'} and not lower_pair:return 'one_piece_already_covers_core'
    distinct_accessories = a == b == 'Accessories' and accessory_role(anchor) != accessory_role(item)
    if a==b and not distinct_accessories:
        if not lower_pair and (a!='Tops' or not (layers_compatible(anchor,item) or layers_compatible(item,anchor))):
            return 'duplicate_garment_role'
    styles={(anchor.style or '').strip().lower(),(item.style or '').strip().lower()}
    if not lower_pair and any(styles=={x.lower(),y.lower()} for x,y in config.catalog_rules.incompatible_style_pairs):
        return 'explicit_style_conflict'
    issues=compatibility_issues([anchor,item],config.compatibility_rules)
    return issues[0] if issues else None


def rank_score(anchor,item,config):
    semantic=cosine(anchor.semantic_vector,item.semantic_vector)
    metadata=metadata_similarity(anchor,item)
    vector=metadata if semantic is None else semantic
    return vector+config.catalog_rules.metadata_weight*metadata+config.catalog_rules.preference_weight*pair_priority(anchor,item,config.compatibility_rules)


def select_catalog(anchor,items,config,taste_profile=None):
    groups=defaultdict(list)
    for item in items:
        if item.id!=anchor.id and not exclusion_reason(anchor,item,config):groups[slot(item)].append(item)
    for group in groups.values():group.sort(key=lambda i:(-(rank_score(anchor,i,config)+0.08*item_taste_score(i,taste_profile)),digest([anchor.id,i.id])))
    result=[anchor]
    required=['Bottoms'] if slot(anchor)=='Tops' else ['Tops'] if slot(anchor)=='Bottoms' else [] if slot(anchor)=='FullBody' else ['Tops','Bottoms','FullBody']
    # Reserve footwear before optional pieces can consume the candidate budget.
    if config.require_shoes and slot(anchor)!='Shoes' and groups.get('Shoes') and len(result)<config.catalog_limit:
        result.append(groups['Shoes'].pop(0))
    reserved=max(1,(config.catalog_limit-1)//2)
    while reserved and len(result)<config.catalog_limit and any(groups.get(r) for r in required):
        for role in required:
            if reserved and len(result)<config.catalog_limit and groups.get(role):
                result.append(groups[role].pop(0));reserved-=1
    while len(result)<config.catalog_limit and any(groups.values()):
        for role in sorted(groups):
            if groups[role] and len(result)<config.catalog_limit:result.append(groups[role].pop(0))
    return result
