"""Explicit wardrobe-library rules, independent of today's weather or a rating cutoff."""
import re
from itertools import combinations
from app.services.layering_support import lower_layer_pair
from app.outfits.config import CompatibilityRules
from app.services.recommendation.rules import recommendation_slot, is_tights
from app.services.occasion_support import effective_occasion


def slot(item):
    return recommendation_slot(item.category, item.subtype)


def accessory_role(item):
    # Separate slots allow a hat + scarf + sunglasses, not two competing hats.
    if is_tights(item):return 'hosiery'
    if item.category == 'Bags':return 'bag'
    return (item.subtype or 'Unknown').strip().lower()


def core_items(items, require_shoes=False):
    # Select a stable minimal independently wearable base. Necessary layers stay.
    from app.outfits.service import structurally_valid
    core_order={'Tops':0,'FullBody':0,'Bottoms':1,'Shoes':2,'Outerwear':3,'Accessories':4}
    garments=sorted([i for i in items if slot(i) in {'Tops','Bottoms','FullBody','Outerwear','Shoes'} or is_tights(i)],
                    key=lambda i:(core_order.get(slot(i),5),i.id))
    for count in range(1,len(garments)+1):
        for selected in combinations(garments,count):
            if structurally_valid(list(selected), require_shoes=require_shoes or any(slot(i)=='Shoes' for i in items)):return list(selected)
    return [i for i in items if slot(i) in {'Tops','Bottoms','FullBody','Shoes'}]


def optional_layer_ids(items, require_shoes=False):
    core={i.id for i in core_items(items, require_shoes=require_shoes)}
    return [i.id for i in items if i.id not in core]


def statement_pattern(item):
    pattern = (item.pattern or '').lower()
    return bool(re.search(r'floral|flower|striped?|plaid|checkered|gingham|graphic|animal|leopard|polka|print', pattern))


def short_bottom(item):
    return slot(item) == 'Bottoms' and (
        (item.subtype or '') in {'Shorts', 'Athletic Shorts', 'Athletic Skirt', 'Mini Skirt'} or
        (item.length or '').lower() == 'thigh'
    )


def puffer(item):
    return slot(item) == 'Outerwear' and bool(re.search(
        r'puffer|\bdown\b', f'{item.subtype or ""} {item.material or ""}'.lower()))


def occasion_labels(item):
    return {x.strip().lower() for x in effective_occasion(item).split(',') if x.strip()}


def season_labels(item):
    labels={x.strip().lower() for x in (item.season or '').split(',') if x.strip()}
    return labels & {'spring','summer','fall','winter'}


def athletic(item):
    return item.category == 'Activewear' or item.subtype in {
        'Sports Bra', 'Workout Top', 'Workout Leggings', 'Yoga Pants', 'Track Pants',
        'Athletic Shorts', 'Athletic Skirt', 'Athletic Jacket',
    }


def ski(item):
    return item.subtype in {'Ski Jacket', 'Ski Pants', 'Ski Suit'}


def office_or_formal(item):
    # Multiple signals, never a color or a disjoint occasion label alone.
    return item.subtype == 'Pencil Skirt' or (
        item.formality_score is not None and item.formality_score >= 4 and
        (bool(occasion_labels(item) & {'work', 'business', 'formal'}) or
         (item.style or '').lower() in {'business', 'formal'})
    )


def compatibility_issues(items, rules=None):
    rules = rules or CompatibilityRules()
    issues = []
    if rules.block_double_statement_patterns and any(statement_pattern(i) for i in items if slot(i) == 'Tops') and any(
        statement_pattern(i) for i in items if slot(i) == 'Bottoms'
    ):
        issues.append('Both top and bottom have statement patterns; pair a pattern with a plain garment.')
    if rules.block_thermal_conflicts and any(short_bottom(i) for i in items) and any(puffer(i) for i in items):
        issues.append('Do not combine a puffer/down jacket with shorts or a short skirt.')
    tops = [i for i in items if slot(i) == 'Tops']
    bottoms = [i for i in items if slot(i) == 'Bottoms']
    if rules.block_thermal_conflicts:
        # Check opposite body regions; a light inner top under a warm coat is normal.
        upper = tops + [i for i in items if slot(i) == 'Outerwear']
        def extreme_pair(a, b):
            return (a.warmth_level is not None and b.warmth_level is not None and
                    a.warmth_level >= rules.very_warm_minimum and
                    b.warmth_level <= rules.very_light_maximum)
        if any(extreme_pair(a, b) or extreme_pair(b, a) for a in upper for b in bottoms):
            issues.append('Upper and lower garments have conflicting extreme insulation levels.')
        thermal_items=[i for i in items if slot(i) in {'Tops','Bottoms','FullBody','Outerwear','Shoes'}]
        known_seasons=[season_labels(i) for i in thermal_items if season_labels(i)]
        warmth=[i.warmth_level for i in thermal_items if i.warmth_level is not None]
        if len(known_seasons)>=2 and not set.intersection(*known_seasons) and warmth and max(warmth)-min(warmth)>=2:
            issues.append('Items have no shared season and materially conflicting warmth levels.')
    if rules.block_purpose_conflicts:
        lower_bases = {i.id for i in items if any(lower_layer_pair(i,other) for other in items if other.id!=i.id)}
        garments = [i for i in items if slot(i) in {'Tops', 'Bottoms', 'FullBody', 'Outerwear'} and i.id not in lower_bases]
        if any(athletic(i) for i in garments) and any(office_or_formal(i) and not athletic(i) for i in garments):
            issues.append('Dedicated athletic clothing conflicts with office/formal clothing.')
        if any(ski(i) for i in garments) and any(short_bottom(i) for i in garments):
            issues.append('Ski clothing conflicts with shorts or a short skirt.')
    return issues


def pair_priority(anchor, candidate, rules=None):
    """Rank catalog candidates, not admission. Color alone never determines formality."""
    score = 0.0
    if compatibility_issues([anchor, candidate], rules):
        score -= 20
    if statement_pattern(anchor) and (candidate.pattern or '').lower() in {'solid', 'plain'}:
        score += 4
    if anchor.formality_score is not None and candidate.formality_score is not None:
        score += 3 - abs(anchor.formality_score - candidate.formality_score)
    occasions = lambda i: {x.strip().lower() for x in effective_occasion(i).split(',') if x.strip()}
    score += min(len(occasions(anchor) & occasions(candidate)), 2)
    if anchor.style and anchor.style == candidate.style:
        score += 1
    # Ensure this classic pairing is considered before optional decorative pieces.
    for skirt, shirt in [(anchor, candidate), (candidate, anchor)]:
        if (skirt.subtype == 'Pencil Skirt' and 'black' in skirt.color.lower().split(', ')
            and shirt.subtype in {'Blouse', 'Shirt', 'Button-down Shirt'}
            and 'white' in shirt.color.lower().split(', ') and not statement_pattern(shirt)):
            score += 6
    return score
