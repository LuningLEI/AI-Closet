"""Rank saved outfits; never generate fresh garment combinations here."""
import hashlib
from pathlib import Path
from datetime import datetime,timezone
from app.core.constants import (
    EXPOSED_WARM_WEATHER_MIN_F,
    SUMMER_SEASON_MIN_F,
    TEMPERATURE_BOUNDARY_BLEND_F,
    WINTER_SEASON_MAX_F,
)
from app.outfits.config import load_config
from app.outfits.store import build_store
from app.outfits.service import OutfitLibrary
from app.outfits.personal import PersonalOutfits
from app.outfits.compatibility import compatibility_issues
from app.outfits.service import structurally_valid
from app.services.recommendation.rules import occasion_tokens,recommendation_slot,profile_memory_text
from app.services.embedding_service import recommendation_context_text
from app.services.occasion_support import occasion_for_display
from app.services.occasion_thresholds import resolve_thresholds
from app.services.taxonomy import merge_preferences
from app.services.taste_profile_service import TasteProfileService
from app.services.personalization_settings import (
    effective_temperature_f,
    exploration_rate,
    resolve_personalization_settings,
)
from app.services.layering_fit import assess_outfit_layering
from pydantic import BaseModel,Field,model_validator

class WearPolicy(BaseModel):
    wear_exclusion_days: float = Field(default=2,ge=0)
    wear_penalty_points: float = Field(default=40,ge=0)
    wear_penalty_half_life_days: float = Field(default=3,gt=0)
    wear_penalty_cutoff_days: float = Field(default=14,gt=0)
    @model_validator(mode='after')
    def valid_window(self):
        if self.wear_penalty_cutoff_days<=self.wear_exclusion_days:raise ValueError('Cutoff must exceed exclusion period')
        return self

def load_policy():
    return WearPolicy.model_validate_json(Path(__file__).with_name('recommendation_policy.json').read_text())

def policy_for_rotation(level):
    if level == 'repeat_freely':
        return WearPolicy(wear_exclusion_days=0, wear_penalty_points=0,
                          wear_penalty_half_life_days=1, wear_penalty_cutoff_days=1)
    if level == 'more_variety':
        return WearPolicy(wear_exclusion_days=3, wear_penalty_points=50,
                          wear_penalty_half_life_days=5, wear_penalty_cutoff_days=21)
    return load_policy()


def rotate_near_tied_results(results, uid, rotation_seed, limit, level='balanced'):
    """Shuffle only the quality-equivalent head of an already ranked list.

    The seed belongs to one page load, so a network retry is stable while a
    later page load can expose a different set.  Candidates outside the score
    window retain their original order and cannot jump into the head.
    """
    if not rotation_seed or limit < 1 or len(results) < 2:
        return results
    score_window = {
        'repeat_freely': 3.0,
        'balanced': 5.0,
        'more_variety': 8.0,
    }.get(level, 5.0)
    top_score = results[0].score
    pool_limit = max(limit * 4, 20)
    pool = [
        result for result in results[:pool_limit]
        if top_score - result.score <= score_window
    ]
    if len(pool) < 2:
        return results
    pool_ids = {result.id for result in pool}
    pool.sort(key=lambda result: hashlib.sha256(
        f"recommendation-rotation-v1:{uid}:{rotation_seed}:{result.id}".encode()
    ).hexdigest())
    return pool + [result for result in results if result.id not in pool_ids]


def _stable_probability(seed, key):
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _season_probabilities(temperature_f):
    margin = TEMPERATURE_BOUNDARY_BLEND_F
    if temperature_f <= WINTER_SEASON_MAX_F - margin:
        return {"winter": 1.0, "spring": 0.0, "fall": 0.0, "summer": 0.0}
    if temperature_f < WINTER_SEASON_MAX_F + margin:
        spring_fall = (temperature_f - (WINTER_SEASON_MAX_F - margin)) / (2 * margin)
        return {
            "winter": 1.0 - spring_fall,
            "spring": spring_fall,
            "fall": spring_fall,
            "summer": 0.0,
        }
    if temperature_f <= SUMMER_SEASON_MIN_F - margin:
        return {"winter": 0.0, "spring": 1.0, "fall": 1.0, "summer": 0.0}
    if temperature_f < SUMMER_SEASON_MIN_F + margin:
        summer = (temperature_f - (SUMMER_SEASON_MIN_F - margin)) / (2 * margin)
        return {
            "winter": 0.0,
            "spring": 1.0 - summer,
            "fall": 1.0 - summer,
            "summer": summer,
        }
    return {"winter": 0.0, "spring": 0.0, "fall": 0.0, "summer": 1.0}


def _exposed_clothing_probability(temperature_f):
    margin = TEMPERATURE_BOUNDARY_BLEND_F
    if temperature_f <= EXPOSED_WARM_WEATHER_MIN_F - margin:
        return 0.0
    if temperature_f >= EXPOSED_WARM_WEATHER_MIN_F + margin:
        return 1.0
    return (temperature_f - (EXPOSED_WARM_WEATHER_MIN_F - margin)) / (2 * margin)


def temperature_eligible_results(results, temperature_f, selection_seed="stable"):
    """Keep only outfits that are wearable in the active temperature context.

    This is a request-time eligibility gate, not a mutation of the saved
    outfit library.  An outfit rejected here remains available when a later
    request uses a compatible temperature.
    """
    eligible = []
    season_probabilities = _season_probabilities(temperature_f)
    exposed_probability = _exposed_clothing_probability(temperature_f)
    for result in results:
        if result.breakdown.weather_fit < 12:
            continue
        if temperature_f < WINTER_SEASON_MAX_F and "outerwear" in result.missing_slots:
            continue
        items = list(getattr(result, "items", []))
        has_outerwear = any(
            recommendation_slot(getattr(item, "category", ""), getattr(item, "subtype", None)) == "Outerwear"
            for item in items
        )
        season_probability = 1.0
        has_exposed_piece = False
        for item in items:
            item_seasons = {
                token.strip().lower().replace(" ", "-")
                for token in getattr(item, "season", "").split(",")
                if token.strip()
            }
            if item_seasons:
                item_probability = min(1.0, sum(
                    season_probabilities.get(season, 0.0)
                    for season in item_seasons
                ))
                season_probability = min(season_probability, item_probability)
            subtype = (getattr(item, "subtype", None) or "").lower()
            sleeve = (getattr(item, "sleeve_length", None) or "").lower()
            is_exposed_top = (
                sleeve in {"sleeveless", "short sleeve", "strapless", "spaghetti strap"}
                or (not sleeve and subtype in {
                    "t-shirt", "tank top", "tube top", "camisole", "sports bra"
                })
            )
            is_shorts = subtype in {"shorts", "athletic shorts"}
            has_exposed_piece = has_exposed_piece or is_shorts or (is_exposed_top and not has_outerwear)
        if season_probability <= 0:
            continue
        if season_probability < 1 and _stable_probability(
            selection_seed, f"season:{result.id}"
        ) >= season_probability:
            continue
        if has_exposed_piece:
            if exposed_probability <= 0:
                continue
            if exposed_probability < 1 and _stable_probability(
                selection_seed, f"exposed:{result.id}"
            ) >= exposed_probability:
                continue
        eligible.append(result)
    return eligible


def _occasion_match_strength(item, requested):
    """Return 2 for a direct/peer match, 1 for a safe everyday fallback."""
    requested = (requested or "Everyday").strip().lower()
    available = occasion_tokens(getattr(item, "occasion", ""))
    if requested == "everyday":
        return 2 if available.intersection({"everyday", "travel", "work"}) else 0
    if requested in available:
        return 2
    if requested in {"date", "party"} and available.intersection({"date", "party"}):
        return 2
    if requested in {"work", "school", "travel", "date", "party"} and "everyday" in available:
        return 1
    return 0


def occasion_eligible_results(results, requested, limit=5):
    """Build an occasion-compatible pool before page rotation.

    Outfit-library visual approval is context-free.  Today requests therefore
    need a request-time gate just like temperature: a high static score must
    not keep an outfit whose core garments are wrong for the selected occasion.
    Direct matches are preferred; safe Everyday fallbacks only fill a short
    page for Work, School, or Travel.
    """
    direct = set()
    fallback = set()
    passthrough = set()
    for result in results:
        core = [
            item for item in getattr(result, "items", [])
            if recommendation_slot(item.category, item.subtype) in {"Tops", "Bottoms", "FullBody"}
        ]
        if not core:
            # Explicit personal compositions can intentionally be non-standard.
            # Their context score may move them down, but request-time policy
            # must not make them disappear solely for lacking a core slot.
            passthrough.add(result.id)
            continue
        strengths = [_occasion_match_strength(item, requested) for item in core]
        if not all(strengths):
            continue
        if any(strength == 2 for strength in strengths):
            direct.add(result.id)
        else:
            fallback.add(result.id)

    admitted = direct | passthrough
    if len(admitted) < limit:
        admitted |= fallback
    return [result for result in results if result.id in admitted]


def _core_item_ids(result):
    return {
        item.id for item in getattr(result, "items", [])
        if recommendation_slot(item.category, item.subtype) in {"Tops", "Bottoms", "FullBody"}
    }


def _outerwear_item_ids(result):
    return {
        item.id for item in getattr(result, "items", [])
        if recommendation_slot(item.category, item.subtype) == "Outerwear"
    }


def _base_outfit_id(result):
    return getattr(result, "outfit_id", None) or result.id.split(":", 1)[0]


def _has_short_lower_body(result):
    short_subtypes = {"Shorts", "Athletic Shorts", "Athletic Skirt", "Mini Skirt"}
    for item in getattr(result, "items", []):
        slot = recommendation_slot(item.category, item.subtype)
        if slot in {"Bottoms", "FullBody"} and (
            (item.subtype or "") in short_subtypes
            or (item.length or "").lower() == "thigh"
        ):
            return True
    return False


def stratified_score_rotation(results, uid, rotation_seed, limit, temperature_f=None):
    """Sample a page across score bands while preserving quality and safety.

    A five-result page contains four candidates from the high-score third and
    one from the middle third.  The low-score third is not sampled.  The caller
    must apply hard eligibility gates before this presentation-only sampling.
    A page seed makes retries stable while a new page load produces a new mix.
    """
    if not rotation_seed or limit < 5 or len(results) <= limit:
        return results

    count = len(results)
    high_end = max(1, (count + 2) // 3)
    middle_end = max(high_end + 1, (2 * count + 2) // 3)
    bands = [
        list(results[:high_end]),
        list(results[high_end:middle_end]),
        list(results[middle_end:]),
    ]

    def seeded_order(rows, band):
        return sorted(rows, key=lambda row: hashlib.sha256(
            f"recommendation-score-band-v1:{uid}:{rotation_seed}:{band}:{row.id}".encode()
        ).hexdigest())

    bands = [seeded_order(rows, index) for index, rows in enumerate(bands)]
    high_quota = limit - 1
    middle_quota = 1
    quotas = [high_quota, middle_quota, 0]

    selected = []
    selected_ids = set()
    selected_core_ids = set()
    selected_outerwear_counts = {}
    selected_base_counts = {}
    short_lower_count = 0
    short_lower_limit = 2

    def take(rows, quota, allow_outerwear_relaxation=False):
        nonlocal short_lower_count
        chosen = []
        # Prefer distinct tops/bottoms and cap short lower-body silhouettes in
        # mild weather. Relax only when the user's library cannot fill a band.
        passes = [
            (1, 1, True, True),
            (1, 1, True, False),
            (1, 1, False, False),
        ]
        if allow_outerwear_relaxation:
            passes.extend([
                (2, 2, True, False),
                (2, 2, False, False),
                (None, None, False, False),
            ])
        for outerwear_limit, base_limit, enforce_core, enforce_coverage in passes:
            for row in rows:
                if len(chosen) >= quota or row.id in selected_ids:
                    continue
                core_ids = _core_item_ids(row)
                outerwear_ids = _outerwear_item_ids(row)
                base_id = _base_outfit_id(row)
                is_short_lower = _has_short_lower_body(row)
                if enforce_core and core_ids.intersection(selected_core_ids):
                    continue
                if base_limit is not None and selected_base_counts.get(base_id, 0) >= base_limit:
                    continue
                if outerwear_limit is not None and any(
                    selected_outerwear_counts.get(item_id, 0) >= outerwear_limit
                    for item_id in outerwear_ids
                ):
                    continue
                if enforce_coverage and is_short_lower and short_lower_count >= short_lower_limit:
                    continue
                chosen.append(row)
                selected_ids.add(row.id)
                selected_core_ids.update(core_ids)
                for item_id in outerwear_ids:
                    selected_outerwear_counts[item_id] = selected_outerwear_counts.get(item_id, 0) + 1
                selected_base_counts[base_id] = selected_base_counts.get(base_id, 0) + 1
                short_lower_count += int(is_short_lower)
        return chosen

    for rows, quota in zip(bands, quotas):
        selected.extend(take(rows, quota))

    # Small libraries or uneven bands should still return a full page.
    if len(selected) < limit:
        fallback = seeded_order(
            [row for row in results if row.id not in selected_ids],
            "fallback",
        )
        additions = take(fallback, limit - len(selected), allow_outerwear_relaxation=True)
        selected.extend(additions)
    selected.sort(key=lambda row: (-row.score, row.id))
    return selected + [row for row in results if row.id not in selected_ids]

def wear_effect(items,events,policy,now=None):
    now=now or datetime.now(timezone.utc)
    ids={i.id for i in items};last=[]
    for e in events:
        if ids.intersection(e['item_ids']):
            t=datetime.fromisoformat(e['worn_at'].replace('Z','+00:00'))
            if t.tzinfo is None:raise ValueError('Wear timestamp requires timezone')
            last.append(t)
    if not last:return False,0.0
    age=max(0,(now-max(last)).total_seconds()/86400)
    if age<policy.wear_exclusion_days:return True,policy.wear_penalty_points
    if age>=policy.wear_penalty_cutoff_days:return False,0.0
    return False,policy.wear_penalty_points*2**(-(age-policy.wear_exclusion_days)/policy.wear_penalty_half_life_days)

class SavedCandidate:
    def __init__(self,oid,items):
        self.identifier=oid;self.items=items
        for role,attr in [('Tops','top'),('Bottoms','bottom'),('FullBody','full_body'),('Shoes','shoes'),('Outerwear','outerwear'),('Accessories','accessory')]:
            setattr(self,attr,next((i for i in items if recommendation_slot(i.category,i.subtype)==role),None))

class IdentitySigner:
    def items(self,items,base_url):return items

def recommend_library(repository,engine,uid,context,preferences):
    store=build_store(repository);lib=OutfitLibrary(repository,store,load_config())
    personal=PersonalOutfits(repository,store)
    preferences=merge_preferences(preferences)
    settings=resolve_personalization_settings(preferences)
    use_learned_taste=settings.personalization_enabled and settings.feedback_learning_enabled
    taste=TasteProfileService(store).ensure_current(uid) if use_learned_taste else {}
    outfits=[];offset=0
    if hasattr(store,'projected_page'):
        while True:
            page=lib.list(uid,IdentitySigner(),'',offset=offset,limit=100)
            outfits.extend(page.outfits)
            if page.next_offset is None:break
            offset=page.next_offset
    else:
        outfits=lib._records_list(uid,IdentitySigner(),'',limit=10_000_000).outfits+personal.list(uid)
    current={i.id:i for i in repository.list_items_for_recommendation(uid)} if outfits else {}
    thresholds=resolve_thresholds(preferences)
    events=personal.rows('outfit_wear_events',uid);policy=policy_for_rotation(settings.rotation_level)
    disliked=personal.disliked_signatures(uid)
    candidates=[];seen=set()
    for outfit in outfits:
        if outfit.source!='personal' and outfit.visual_review_status!='passed':continue
        sets=[outfit.items]+[outfit.items+v.items for v in outfit.optional_additions if v.visual_review_status=='passed']
        for members in sets:
            if any(i.id not in current for i in members):continue
            members=list({i.id:current[i.id] for i in members}.values())
            layering = assess_outfit_layering(members, lib.config.layering_fit_policy)
            # A personal outfit is an explicit user decision. Preserve and rank it
            # exactly as saved; generated outfits still obey system validation.
            if (outfit.source != 'personal'
                    and (not structurally_valid(members, require_shoes=lib.config.require_shoes)
                         or compatibility_issues(members, lib.config.compatibility_rules)
                         or (layering and layering.hard_failure))):
                continue
            signature=tuple(sorted(i.id for i in members))
            if personal.composition_signature(signature) in disliked:continue
            if signature in seen:continue
            seen.add(signature)
            blocked,penalty=wear_effect(members,events,policy)
            if blocked:continue
            candidate=SavedCandidate(outfit.id,[occasion_for_display(i,thresholds) for i in members])
            candidates.append((candidate,penalty,outfit.source=='personal'))
    if not candidates:return []
    vector=None
    if any(i.semantic_vector for c,_,_ in candidates for i in c.items):
        profile_context = profile_memory_text(preferences, context.occasion) if settings.personalization_enabled else ''
        vector=engine.embedding_service.create_embedding(recommendation_context_text(context)+' '+profile_context)
    results=[]
    for candidate,penalty,trusted_user_outfit in candidates:
        result=engine.scorer.score(
            candidate,
            context,
            vector,
            preferences,
            trusted_user_outfit=trusted_user_outfit,
            prevalidated_library_outfit=not trusted_user_outfit,
            taste_profile=taste,
        )
        if result is None:continue
        result.original_score=round(result.score-result.personalization_score,2)
        result.wear_penalty=round(penalty,2)
        result.score=round(max(0,result.score-penalty),2)
        # Distinguish optional variants while preserving the library identity.
        result.outfit_id=candidate.identifier
        result.id=candidate.identifier+':'+','.join(sorted(i.id for i in candidate.items))
        results.append(result)
    results.sort(key=lambda r:(-r.score,r.id))
    styling_temperature = effective_temperature_f(context.temperature_f, settings)
    rotation_seed = getattr(context,'rotation_seed',None)
    temperature_seed = f"{uid}:{rotation_seed or context.occasion}"
    results = temperature_eligible_results(results, styling_temperature, temperature_seed)
    results = occasion_eligible_results(results, context.occasion, context.limit)
    results = stratified_score_rotation(
        results,
        uid,
        rotation_seed,
        context.limit,
        styling_temperature,
    )
    memory=taste.get('generation_memory') or {}
    rate=exploration_rate(settings) if settings.personalization_enabled else 0.0
    if (not getattr(context,'rotation_seed',None)
            and memory.get('evidence_threshold_met') and rate > 0
            and len(results)>context.limit and context.limit>=5):
        quota=max(1,round(context.limit*rate))
        head=results[:max(0,context.limit-quota)]
        rest=results[max(0,context.limit-quota):]
        seed=f"{uid}:{datetime.now(timezone.utc).date()}:{context.occasion}"
        rest.sort(key=lambda row:hashlib.sha256(f"{seed}:{row.id}".encode()).hexdigest())
        results=head+rest[:quota]
    return engine._diversify(results,context.limit)[:context.limit]
