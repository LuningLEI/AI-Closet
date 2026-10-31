"""Deterministic, replayable per-user taste learning. No model calls."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil, sqrt
from typing import Any
import json

from app.outfits.config import digest

ALGORITHM_VERSION = "taste-profile-v2"
HALF_LIFE_DAYS = 270.0
DECAY_FLOOR = 0.0
EXPLORATION_RATE = 0.15
GENERATION_EVIDENCE_THRESHOLD = 2
GENERATION_WEAR_THRESHOLD = 2
LATENT_CLUSTER_THRESHOLD = 20
MAX_PERSONALIZATION_SCORE = 20.0
FREE_TEXT_SUMMARY_THRESHOLD = 10
FREE_TEXT_SUMMARY_BATCH_SIZE = 50


@dataclass(frozen=True)
class TasteLearningConfig:
    """Tunable reducer parameters with production defaults kept in one place.

    The simulation passes explicit alternatives. Normal application calls omit
    this object and therefore use the production taste-profile-v2 defaults.
    """

    personal_strength: float = 2.0
    wear_strength: float = 1.5
    liked_strength: float = 1.0
    disliked_strength: float = -1.0
    half_life_days: float = HALF_LIFE_DAYS
    decay_floor: float = DECAY_FLOOR
    exploration_rate: float = EXPLORATION_RATE
    generation_evidence_threshold: int = GENERATION_EVIDENCE_THRESHOLD
    generation_wear_threshold: int = GENERATION_WEAR_THRESHOLD
    latent_cluster_threshold: int = LATENT_CLUSTER_THRESHOLD
    prior_strength: float = 2.5
    personalization_scale: float = 0.5
    maximum_personalization_score: float = MAX_PERSONALIZATION_SCORE

    @property
    def source_strength(self) -> dict[str, float]:
        return {"personal": self.personal_strength, "wear": self.wear_strength,
                "liked": self.liked_strength, "disliked": self.disliked_strength}


DEFAULT_TASTE_LEARNING_CONFIG = TasteLearningConfig()

SOURCE_STRENGTH = {"personal": 2.0, "wear": 1.5, "liked": 1.0, "disliked": -1.0}
ITEM_FIELDS = ("id", "category", "subtype", "color", "style", "occasion", "season",
               "material", "pattern", "fit", "length", "sleeve_length", "layering_role",
               "warmth_level", "formality_score")

REASON_PREFIXES = {
    "color_pattern": ("color:", "color_pair:", "pattern:", "pattern_balance:"),
    "style": ("style:", "style_pair:", "category:", "category_pair:", "subtype:", "subtype_pair:"),
    "too_formal": ("formality:",), "too_casual": ("formality:",),
    "weather_mismatch": ("warmth:", "season:", "occasion_warmth:"),
    "occasion_mismatch": ("occasion:", "occasion_style:", "occasion_category:"),
    "pieces_do_not_match": ("color_pair:", "style_pair:", "category_pair:", "subtype_pair:", "pattern_balance:"),
    "layering": ("layering:",),
    "shoes_accessories": ("shoe:", "accessory:", "category_pair:shoes", "subtype_pair:shoes"),
    "dislike_item": ("item:",),
    "too_repetitive": (), "other": (),
}


def _tokens(value: Any) -> list[str]:
    if isinstance(value, list): raw = value
    else: raw = str(value or "").split(",")
    return sorted({str(token).strip().casefold().replace(" ", "_") for token in raw
                   if str(token).strip() and str(token).strip().casefold() not in {"unknown", "none"}})


def _bucket(value: Any) -> str | None:
    try: number = int(value)
    except (TypeError, ValueError): return None
    return "low" if number <= 2 else "medium" if number == 3 else "high"


def snapshot_items(items, context: dict | None = None) -> dict:
    rows = []
    vectors = []
    for item in items:
        row = {field: getattr(item, field, None) for field in ITEM_FIELDS}
        vector = getattr(item, "semantic_vector", None)
        if isinstance(vector, list) and vector and all(isinstance(value, (int, float)) for value in vector):
            vectors.append(vector)
        rows.append(row)
    dimensions = {len(vector) for vector in vectors}
    centroid = None
    if len(dimensions) == 1:
        size = dimensions.pop()
        centroid = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(size)]
    return {"items": rows, "context": context or {}, "outfit_vector": centroid}


def snapshot_features(snapshot: dict) -> dict[str, float]:
    items = snapshot.get("items") if isinstance(snapshot, dict) else None
    if not isinstance(items, list): return {}
    features: dict[str, float] = {}
    values: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if not isinstance(item, dict): continue
        item_id = str(item.get("id") or "").casefold()
        if item_id: features[f"item:{item_id}"] = 1.0
        category = next(iter(_tokens(item.get("category"))), "")
        subtype = next(iter(_tokens(item.get("subtype"))), "")
        # Keep auxiliary-item signals available for a later feature, while the
        # current release personalizes clothing only.
        if category == "shoes":
            if subtype: features[f"shoe:{subtype}"] = 1.0
            continue
        if category in {"bags", "accessories"}:
            if subtype: features[f"accessory:{subtype}"] = 1.0
            continue
        for field in ("category", "subtype", "color", "style", "occasion", "season", "pattern"):
            for token in _tokens(item.get(field)):
                features[f"{field}:{token}"] = 1.0
                values[field].append(token)
        for field in ("warmth_level", "formality_score"):
            if bucket := _bucket(item.get(field)): features[f"{field.removesuffix('_level').removesuffix('_score')}:{bucket}"] = 1.0
    for field in ("category", "subtype", "color", "style"):
        unique = sorted(set(values[field]))
        for left_index, left in enumerate(unique):
            for right in unique[left_index + 1:]: features[f"{field}_pair:{left}+{right}"] = 1.0
    patterns = [value for value in values["pattern"] if value not in {"solid", "plain"}]
    features["pattern_balance:multiple_statement" if len(patterns) > 1 else "pattern_balance:balanced"] = 1.0
    categories = values["category"]
    top_count = sum(value in {"tops", "outerwear"} for value in categories)
    bottom_count = sum(value == "bottoms" for value in categories)
    if top_count > 1: features["layering:upper"] = 1.0
    if bottom_count > 1 or "tights" in values["subtype"]: features["layering:lower"] = 1.0
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    occasion = next(iter(_tokens(context.get("occasion"))), None)
    if occasion:
        features[f"occasion:{occasion}"] = 1.0
        for style in sorted(set(values["style"])): features[f"occasion_style:{occasion}|{style}"] = 1.0
        for category in sorted(set(categories)): features[f"occasion_category:{occasion}|{category}"] = 1.0
    return features


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime): result = value
    elif isinstance(value, str): result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else: result = datetime.now(timezone.utc)
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def decay_factor(created_at: Any, now: datetime,
                 config: TasteLearningConfig = DEFAULT_TASTE_LEARNING_CONFIG) -> float:
    age = max(0.0, (now - _parse_time(created_at).astimezone(timezone.utc)).total_seconds() / 86400)
    return config.decay_floor + (1.0 - config.decay_floor) * 2 ** (-age / config.half_life_days)


def _scoped(features: dict[str, float], reasons: list[str], target_ids: list[str]) -> dict[str, float]:
    if not reasons: return {}
    prefixes = tuple(prefix for reason in reasons for prefix in REASON_PREFIXES.get(reason, ()))
    if not prefixes: return {}
    selected = {key: value for key, value in features.items() if key.startswith(prefixes)}
    if "dislike_item" in reasons and target_ids:
        selected.update({f"item:{item_id.casefold()}": 1.0 for item_id in target_ids})
    return selected


def _centroid(weighted_vectors: list[tuple[list[float], float]]) -> list[float] | None:
    dimensions = {len(vector) for vector, _ in weighted_vectors if vector}
    if len(dimensions) != 1: return None
    size = dimensions.pop(); total = sum(weight for _, weight in weighted_vectors)
    if not total: return None
    return [sum(vector[index] * weight for vector, weight in weighted_vectors) / total for index in range(size)]


def _vector(value: Any) -> list[float] | None:
    if isinstance(value, str):
        try: value = json.loads(value)
        except (TypeError, ValueError): return None
    return value if isinstance(value, list) and value and all(isinstance(part, (int, float)) for part in value) else None


def reduce_sources(sources: list[dict], *, now: datetime | None = None,
                   config: TasteLearningConfig = DEFAULT_TASTE_LEARNING_CONFIG) -> dict:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evidence: dict[str, dict] = {}
    positive_vectors, negative_vectors = [], []
    latent: dict[str, dict] = {}
    free_text_count = 0
    for source in sorted(sources, key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or ""))):
        kind = str(source.get("kind") or "")
        snapshot = source.get("feature_snapshot") or {}
        features = snapshot_features(snapshot)
        strength = config.source_strength.get(kind, 0.0)
        reasons = source.get("reason_codes") or []
        if source.get("note"): free_text_count += 1
        if kind == "disliked" and not reasons:
            signature = digest(sorted(key for key in features if not key.startswith("item:")))
            cluster = latent.setdefault(signature, {"count": 0, "sample_features": sorted(features)[:12]})
            cluster["count"] += 1
            continue
        if kind == "disliked": features = _scoped(features, reasons, source.get("target_item_ids") or [])
        if not features: continue
        factor = decay_factor(source.get("created_at"), now, config)
        weighted = strength * factor
        for key, value in features.items():
            row = evidence.setdefault(key, {"positive": 0.0, "negative": 0.0, "count": 0,
                                           "wear_count": 0, "latest_at": None})
            if weighted >= 0: row["positive"] += weighted * value
            else: row["negative"] += -weighted * value
            row["count"] += 1
            if kind == "wear": row["wear_count"] += 1
            row["latest_at"] = max(filter(None, [row["latest_at"], source.get("created_at")]), default=None)
        vector = _vector(snapshot.get("outfit_vector"))
        if vector:
            (positive_vectors if weighted > 0 else negative_vectors).append((vector, abs(weighted)))
    weights = {}
    for key, row in evidence.items():
        total = row["positive"] + row["negative"]
        confidence = total / (total + config.prior_strength)
        weights[key] = round(max(-1.0, min(1.0, (row["positive"] - row["negative"]) * confidence)), 6)
        row.update({name: round(row[name], 6) for name in ("positive", "negative")})
    eligible = [(key, value) for key, value in weights.items()
                if not key.startswith(("item:", "shoe:", "accessory:")) and
                (evidence[key]["count"] >= config.generation_evidence_threshold
                 or evidence[key]["wear_count"] >= config.generation_wear_threshold)]
    preferred = [key for key, value in sorted(eligible, key=lambda row: (-row[1], row[0])) if value > 0][:20]
    avoid = [key for key, value in sorted(eligible, key=lambda row: (row[1], row[0])) if value < 0][:20]
    clusters = [value for value in latent.values() if value["count"] >= config.latent_cluster_threshold]
    return {"algorithm_version": ALGORITHM_VERSION, "feature_weights": weights, "feature_evidence": evidence,
            "positive_centroid": _centroid(positive_vectors), "negative_centroid": _centroid(negative_vectors),
            "generation_memory": {"preferred": preferred, "avoid": avoid,
                "evidence_threshold_met": bool(preferred or avoid), "exploration_rate": config.exploration_rate,
                "latent_dislike_clusters": sorted(clusters, key=lambda row: -row["count"])},
            "new_free_text_count": free_text_count}


def item_taste_score(item, profile: dict | None,
                     config: TasteLearningConfig = DEFAULT_TASTE_LEARNING_CONFIG) -> float:
    if not profile: return 0.0
    snapshot = snapshot_items([item]); weights = profile.get("feature_weights") or {}
    evidence = profile.get("feature_evidence") or {}
    def eligible(key: str) -> bool:
        row = evidence.get(key) or {}
        return (not key.startswith(("item:", "shoe:", "accessory:"))
                and (row.get("count", 0) >= config.generation_evidence_threshold
                     or row.get("wear_count", 0) >= config.generation_wear_threshold))
    return sum(weights.get(key, 0.0) * value for key, value in snapshot_features(snapshot).items() if eligible(key))


def outfit_taste_score(items, profile: dict | None, context: dict | None = None,
                       config: TasteLearningConfig = DEFAULT_TASTE_LEARNING_CONFIG) -> float:
    if not profile: return 0.0
    snapshot = snapshot_items(items, context); weights = profile.get("feature_weights") or {}
    evidence = profile.get("feature_evidence") or {}
    def eligible(key: str) -> bool:
        row = evidence.get(key) or {}
        return (not key.startswith(("item:", "shoe:", "accessory:"))
                and (row.get("count", 0) >= config.generation_evidence_threshold
                     or row.get("wear_count", 0) >= config.generation_wear_threshold))
    raw = sum(weights.get(key, 0.0) * value for key, value in snapshot_features(snapshot).items() if eligible(key))
    vector = _vector(snapshot.get("outfit_vector"))
    def cosine(other):
        if not vector or not other or len(vector) != len(other): return 0.0
        denominator = sqrt(sum(v*v for v in vector) * sum(v*v for v in other))
        return sum(a*b for a,b in zip(vector, other)) / denominator if denominator else 0.0
    if (profile.get("generation_memory") or {}).get("evidence_threshold_met"):
        raw += 2.0 * cosine(profile.get("positive_centroid")) - 2.0 * cosine(profile.get("negative_centroid"))
    return max(-config.maximum_personalization_score,
               min(config.maximum_personalization_score, raw * config.personalization_scale))


def generation_taste_context(anchor, catalog, profile: dict | None, maximum_outfits: int,
                             config: TasteLearningConfig = DEFAULT_TASTE_LEARNING_CONFIG) -> dict | None:
    """Build enforceable, clothing-only generation guidance from a projected profile."""
    memory = (profile or {}).get("generation_memory") or {}
    summary = (profile or {}).get("free_text_summary") or {}
    if not memory.get("evidence_threshold_met") and not summary:
        return None
    rate = max(0.0, min(1.0, float(memory.get("exploration_rate", config.exploration_rate))))
    target = min(maximum_outfits, ceil(maximum_outfits * rate)) if rate and maximum_outfits else 0
    candidates = []
    for item in catalog:
        if item.id == anchor.id or getattr(item, "category", None) in {"Shoes", "Bags", "Accessories"}:
            continue
        score = item_taste_score(item, profile, config)
        # Exploration means new/less-established territory, never a known negative.
        if score >= 0:
            candidates.append((abs(score), digest([anchor.id, item.id]), item.id))
    # Several IDs give the model room to form a valid outfit while the output quota
    # is still checked after generation.
    neutral = [row for row in candidates if row[0] <= 1e-9]
    pool = neutral or candidates
    exploration_ids = [row[2] for row in sorted(pool)[:max(4, target * 4)]]
    if not exploration_ids:
        target = 0
    return {
        "prefer": memory.get("preferred", []),
        "avoid": memory.get("avoid", []),
        "free_text_summary": summary,
        "exploration_rate": rate,
        "exploration_outfit_count": target,
        "exploration_candidate_ids": exploration_ids,
    }


def exploration_quota_met(proposals, context: dict | None) -> bool:
    """Enforce the discrete exploration quota promised to the generation model."""
    if not context:
        return True
    if not proposals:
        return True
    target = int(context.get("exploration_outfit_count") or 0)
    exploration_ids = set(context.get("exploration_candidate_ids") or [])
    if not target:
        return True
    explored = sum(bool(exploration_ids.intersection(proposal.item_ids)) for proposal in proposals)
    return explored == target


def taste_review_key(profile: dict | None) -> str:
    """Cache reviews only across profiles that send identical Taste evidence."""
    memory = (profile or {}).get("generation_memory") or {}
    return digest({
        "prefer": memory.get("preferred", []) if memory.get("evidence_threshold_met") else [],
        "avoid": memory.get("avoid", []) if memory.get("evidence_threshold_met") else [],
        "free_text_summary": (profile or {}).get("free_text_summary") or {},
    })
