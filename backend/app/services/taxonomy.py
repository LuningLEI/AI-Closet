from __future__ import annotations

from typing import Any

from app.core.constants import DEFAULT_CATEGORY, DEFAULT_OCCASION, DEFAULT_STYLE

CATEGORIES = [
    "Tops",
    "Bottoms",
    "Dresses",
    "Jumpsuits",
    "Sets",
    "Outerwear",
    "Shoes",
    "Bags",
    "Accessories",
    "Activewear",
    "Swimwear",
    "Intimates",
    DEFAULT_CATEGORY,
]
COLORS = [
    "Unknown",
    "Black",
    "White",
    "Gray",
    "Blue",
    "Navy",
    "Red",
    "Green",
    "Olive",
    "Brown",
    "Beige",
    "Pink",
    "Purple",
    "Yellow",
    "Orange",
    "Gold",
    "Silver",
    "Multicolor",
]
STYLES = [
    "Casual",
    "Formal",
    "Business",
    "Sporty",
    "Streetwear",
    "Elegant",
    "Minimalist",
    "Romantic",
    "Classic",
    "Bohemian",
    "Preppy",
    "Edgy",
]
OCCASIONS = ["Everyday", "Work", "Party", "Date", "Travel", "Workout", "Wedding", "Lounge", "Evening"]
SEASONS = ["Spring", "Summer", "Fall", "Winter"]
LENGTHS = ["Cropped", "Hip", "Thigh", "Knee", "Midi", "Maxi", "Full"]
SLEEVE_LENGTHS = ["Sleeveless", "Short Sleeve", "Long Sleeve", "Strapless", "Spaghetti Strap"]

SUBTYPES = {
    "Tops": [
        "Unknown",
        "T-shirt",
        "Tank Top",
        "Tube Top",
        "Mesh Top",
        "Camisole",
        "Blouse",
        "Button-down Shirt",
        "Sweater",
        "Hoodie",
        "Pullover",
        "Bodysuit",
        "Vest",
    ],
    "Bottoms": [
        "Unknown",
        "Jeans",
        "Wide-leg Pants",
        "Straight-leg Pants",
        "Trousers",
        "Joggers",
        "Shorts",
        "Pencil Skirt",
        "Mini Skirt",
        "Midi Skirt",
        "Maxi Skirt",
    ],
    "Dresses": ["Unknown", "Slip Dress", "Shirt Dress", "Wrap Dress", "Sweater Dress", "T-shirt Dress", "A-line Dress"],
    "Jumpsuits": ["Unknown", "Jumpsuit", "Romper"],
    "Sets": ["Unknown", "Two-piece Set", "Suit Set"],
    "Outerwear": ["Unknown", "Vest", "Cape", "Jacket", "Coat", "Blazer", "Cardigan", "Puffer", "Windbreaker", "Trench Coat", "Leather Jacket"],
    "Shoes": ["Unknown", "Sneakers", "Boots", "Sandals", "Heels", "Loafers", "Flats", "Mules", "Slippers"],
    "Bags": ["Unknown", "Tote", "Shoulder Bag", "Crossbody Bag", "Clutch", "Backpack", "Mini Bag"],
    "Accessories": ["Unknown", "Hat", "Scarf", "Belt", "Jewelry", "Watch", "Sunglasses", "Hair Accessory"],
    "Activewear": ["Unknown", "Ski Jacket", "Ski Pants", "Ski Suit", "Athletic Jacket", "Sports Bra", "Workout Top", "Workout Leggings", "Yoga Pants", "Track Pants", "Athletic Shorts", "Athletic Skirt"],
    "Swimwear": ["Unknown", "Bikini", "One-piece Swimsuit", "Cover-up", "Swim Trunks"],
    "Intimates": ["Unknown", "Tights", "Bra", "Underwear", "Loungewear", "Pajamas", "Slip"],
    DEFAULT_CATEGORY: ["Unknown"],
}


def default_user_preferences() -> dict[str, Any]:
    return {
        "onboarding_completed": False,
        "profile": {
            "birth_year": None,
            "gender_identity": None,
            "daily_occasions": [DEFAULT_OCCASION, "Work"],
            "style_preferences": [DEFAULT_STYLE],
            "occasion_style_preferences": {
                DEFAULT_OCCASION: [DEFAULT_STYLE],
                "Work": [DEFAULT_STYLE],
            },
        },
        "taxonomy": {
            "selected_categories": CATEGORIES,
            "custom_categories": [],
            "customizations": {},
        },
    }


def merge_preferences(preferences: dict[str, Any] | None) -> dict[str, Any]:
    merged = default_user_preferences()
    if not isinstance(preferences, dict):
        return merged

    profile = preferences.get("profile")
    taxonomy = preferences.get("taxonomy")
    if isinstance(profile, dict):
        merged["profile"].update(profile)
    if isinstance(taxonomy, dict):
        merged["taxonomy"].update(taxonomy)
    if isinstance(preferences.get("occasion_thresholds"), dict):
        merged["occasion_thresholds"] = dict(preferences["occasion_thresholds"])
    if "onboarding_completed" in preferences:
        merged["onboarding_completed"] = bool(preferences["onboarding_completed"])
    return merged


def preferred_styles_for_occasion(preferences: dict[str, Any] | None, occasion: str | None) -> list[str]:
    """Return the user's styles for this occasion, with legacy-profile fallback."""
    profile = merge_preferences(preferences).get("profile", {})
    mapping = profile.get("occasion_style_preferences") if isinstance(profile, dict) else None
    if occasion and isinstance(mapping, dict):
        target = occasion.strip().casefold()
        for label, styles in mapping.items():
            if isinstance(label, str) and label.strip().casefold() == target and isinstance(styles, list):
                cleaned = [style.strip() for style in styles if isinstance(style, str) and style.strip()]
                if cleaned:
                    return list(dict.fromkeys(cleaned))
    styles = profile.get("style_preferences") if isinstance(profile, dict) else None
    if isinstance(styles, list):
        return list(dict.fromkeys(style.strip() for style in styles if isinstance(style, str) and style.strip()))
    return []


def user_categories(preferences: dict[str, Any] | None) -> list[str]:
    merged = merge_preferences(preferences)
    taxonomy = merged["taxonomy"]
    selected = taxonomy.get("selected_categories") if isinstance(taxonomy, dict) else None
    custom = taxonomy.get("custom_categories") if isinstance(taxonomy, dict) else None

    categories: list[str] = []
    for value in selected if isinstance(selected, list) else CATEGORIES:
        if isinstance(value, str) and value.strip() and value not in categories:
            categories.append(value.strip())
    for value in custom if isinstance(custom, list) else []:
        if isinstance(value, str) and value.strip() and value.strip() not in categories:
            categories.append(value.strip())
    return categories or CATEGORIES


def _clean_options(value: Any, fallback: list[str], *, keep_unknown: bool = False) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    result=[]
    for option in value[:100]:
        if isinstance(option,str) and (label:=option.strip()) and len(label)<=60 and label not in result:
            result.append(label)
    if keep_unknown:
        result=[value for value in result if value!='Unknown']
        result.insert(0,'Unknown')
    return result or list(fallback)


def normalize_customizations(value:Any,categories:list[str]|None=None)->dict[str,Any]:
    if not isinstance(value,dict):return {}
    result={}
    for key in ('colors','styles','occasions','seasons','lengths','sleeve_lengths'):
        if key in value:
            cleaned=_clean_options(value[key],[],keep_unknown=key=='colors')
            if cleaned:result[key]=cleaned
    if isinstance(value.get('subtypes'),dict):
        allowed=set(categories or CATEGORIES);subtypes={}
        for category,options in list(value['subtypes'].items())[:100]:
            if category in allowed:
                subtypes[category]=_clean_options(options,['Unknown'],keep_unknown=True)
        result['subtypes']=subtypes
    return result


def user_taxonomy(preferences: dict[str, Any] | None) -> dict[str, Any]:
    merged=merge_preferences(preferences);categories=user_categories(merged)
    taxonomy=merged.get('taxonomy') or {};custom=normalize_customizations(taxonomy.get('customizations'),categories)
    raw_subtypes=custom.get('subtypes') if isinstance(custom,dict) else None
    subtypes={}
    for category in categories:
        override=raw_subtypes.get(category) if isinstance(raw_subtypes,dict) else None
        subtypes[category]=_clean_options(override,SUBTYPES.get(category,['Unknown']),keep_unknown=True)
    return {
        'categories':categories,
        'subtypes':subtypes,
        'colors':_clean_options(custom.get('colors') if isinstance(custom,dict) else None,COLORS,keep_unknown=True),
        'styles':_clean_options(custom.get('styles') if isinstance(custom,dict) else None,STYLES),
        'occasions':_clean_options(custom.get('occasions') if isinstance(custom,dict) else None,OCCASIONS),
        'seasons':_clean_options(custom.get('seasons') if isinstance(custom,dict) else None,SEASONS),
        'lengths':_clean_options(custom.get('lengths') if isinstance(custom,dict) else None,LENGTHS),
        'sleeve_lengths':_clean_options(custom.get('sleeve_lengths') if isinstance(custom,dict) else None,SLEEVE_LENGTHS),
    }


def user_subtypes(categories: list[str],preferences: dict[str,Any]|None=None) -> dict[str, list[str]]:
    resolved=user_taxonomy(preferences)
    return {category:resolved['subtypes'].get(category,['Unknown']) for category in categories}


# Explicit garment types override a conflicting broad model category. Generic
# silhouettes (tank, T-shirt, wide-leg pants) alone are not athletic evidence.
ACTIVEWEAR_ALIASES = {
    **{name.lower(): name for name in SUBTYPES['Activewear'] if name != 'Unknown'},
    'yoga leggings': 'Yoga Pants', 'yoga trousers': 'Yoga Pants',
    'yoga top': 'Workout Top', 'yoga tank': 'Workout Top',
    'athletic top': 'Workout Top', 'athletic tank': 'Workout Top',
    'athletic t-shirt': 'Workout Top', 'workout tank': 'Workout Top',
    'workout t-shirt': 'Workout Top', 'training top': 'Workout Top',
    'running top': 'Workout Top', 'running shirt': 'Workout Top',
    'track jacket': 'Athletic Jacket', 'training jacket': 'Athletic Jacket',
    'workout jacket': 'Athletic Jacket', 'define jacket': 'Athletic Jacket',
}


def explicit_activewear_subtype(subtype: Any) -> str | None:
    import re
    label = str(subtype or '').strip().lower()
    for alias, canonical in ACTIVEWEAR_ALIASES.items():
        if re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', label):
            return canonical
    return None


def constrain_category(category: str, subtype: Any, allowed_categories: list[str] | None = None) -> str:
    allowed = allowed_categories or CATEGORIES
    if "Activewear" in allowed and explicit_activewear_subtype(subtype):
        return "Activewear"
    if "cardigan" in str(subtype or "").lower() and "Outerwear" in allowed:
        return "Outerwear"
    if "Activewear" in allowed and any(label in str(subtype or "").lower() for label in ("yoga pants", "yoga leggings", "yoga trousers")):
        return "Activewear"
    if category in {"Bottoms", "Activewear"} and "legging" in str(subtype or "").lower() and "Activewear" in allowed:
        return "Activewear"
    if "Activewear" in allowed and any(label in str(subtype or "").lower() for label in ["ski jacket", "ski pants", "ski trousers", "ski suit", "snowsuit"]):
        return "Activewear"
    if category in allowed:
        return category

    normalized = f"{category} {subtype or ''}".lower()
    category_rules = [
        ("Dresses", ["dress", "gown"]),
        ("Jumpsuits", ["jumpsuit", "romper", "playsuit"]),
        ("Sets", ["set", "co-ord", "coord", "matching", "suit set", "two-piece", "two piece"]),
        ("Activewear", ["activewear", "workout", "gym", "sports bra", "athletic"]),
        ("Swimwear", ["swim", "bikini", "swimsuit", "cover-up"]),
        ("Intimates", ["intimate", "bra", "underwear", "pajama", "loungewear"]),
        ("Bags", ["bag", "tote", "clutch", "crossbody", "backpack"]),
        ("Shoes", ["shoe", "sneaker", "boot", "heel", "sandal", "loafer"]),
        ("Outerwear", ["outerwear", "cape", "jacket", "coat", "blazer", "cardigan", "puffer", "trench"]),
        ("Accessories", ["accessor", "scarf", "belt", "hat", "jewelry", "watch", "sunglass"]),
        ("Bottoms", ["bottom", "pants", "trouser", "jean", "shorts", "skirt", "legging", "jogger"]),
        ("Tops", ["top", "shirt", "tee", "t-shirt", "blouse", "sweater", "hoodie", "pullover", "cami"]),
    ]
    for target, needles in category_rules:
        if target in allowed and any(word in normalized for word in needles):
            return target
    if DEFAULT_CATEGORY in allowed:
        return DEFAULT_CATEGORY
    return allowed[0]


def normalize_subtype(category: str, subtype: str | None) -> str | None:
    options = SUBTYPES.get(category, ["Unknown"])
    if not subtype:
        return None if options[0] == "Unknown" else options[0]
    if category == "Activewear" and (athletic := explicit_activewear_subtype(subtype)):
        return athletic
    if subtype in options:
        return None if subtype == "Unknown" else subtype

    lowered = subtype.lower()
    mappings = {
        "Tops": {
            "tube top": "Tube Top",
            "strapless top": "Tube Top",
            "mesh": "Mesh Top",
            "tee": "T-shirt",
            "t-shirt": "T-shirt",
            "tank": "Tank Top",
            "cami": "Camisole",
            "blouse": "Blouse",
            "button": "Button-down Shirt",
            "shirt": "Button-down Shirt",
            "sweater": "Sweater",
            "hoodie": "Hoodie",
            "pullover": "Pullover",
            "bodysuit": "Bodysuit",
            "vest": "Vest",
        },
        "Bottoms": {
            "pencil": "Pencil Skirt",
            "wide": "Wide-leg Pants",
            "straight": "Straight-leg Pants",
            "jean": "Jeans",
            "trouser": "Trousers",
            "pant": "Trousers",
            "jogger": "Joggers",
            "short": "Shorts",
            "mini skirt": "Mini Skirt",
            "midi skirt": "Midi Skirt",
            "maxi skirt": "Maxi Skirt",
            "skirt": "Midi Skirt",
        },
        "Dresses": {
            "slip": "Slip Dress", "t-shirt": "T-shirt Dress", "tee": "T-shirt Dress",
            "sweater": "Sweater Dress", "knit": "Sweater Dress", "shirt": "Shirt Dress",
            "wrap": "Wrap Dress", "a-line": "A-line Dress", "a line": "A-line Dress",
        },
        "Jumpsuits": {
            "jumpsuit": "Jumpsuit",
            "romper": "Romper",
            "playsuit": "Romper",
        },
        "Sets": {
            "two-piece": "Two-piece Set",
            "two piece": "Two-piece Set",
            "suit": "Suit Set",
            "matching": "Two-piece Set",
            "coord": "Two-piece Set",
            "co-ord": "Two-piece Set",
        },
        "Shoes": {
            "sneaker": "Sneakers",
            "boot": "Boots",
            "sandal": "Sandals",
            "heel": "Heels",
            "pump": "Heels",
            "loafer": "Loafers",
            "flat": "Flats",
            "mule": "Mules",
            "slipper": "Slippers",
        },
        "Outerwear": {
            "vest": "Vest",
            "gilet": "Vest",
            "cape": "Cape",
            "jacket": "Jacket",
            "coat": "Coat",
            "blazer": "Blazer",
            "cardigan": "Cardigan",
            "puffer": "Puffer",
            "windbreaker": "Windbreaker",
            "trench": "Trench Coat",
            "leather": "Leather Jacket",
        },
        "Bags": {
            "tote": "Tote",
            "shoulder": "Shoulder Bag",
            "crossbody": "Crossbody Bag",
            "clutch": "Clutch",
            "backpack": "Backpack",
            "mini": "Mini Bag",
            "bag": "Unknown",
        },
        "Accessories": {
            "hat": "Hat",
            "scarf": "Scarf",
            "belt": "Belt",
            "jewel": "Jewelry",
            "watch": "Watch",
            "sunglass": "Sunglasses",
            "hair": "Hair Accessory",
        },
        "Activewear": {
            "ski jacket": "Ski Jacket",
            "ski pants": "Ski Pants",
            "ski trousers": "Ski Pants",
            "ski suit": "Ski Suit",
            "snowsuit": "Ski Suit",
            "athletic jacket": "Athletic Jacket",
            "track jacket": "Athletic Jacket",
            "training jacket": "Athletic Jacket",
            "workout jacket": "Athletic Jacket",
            "define jacket": "Athletic Jacket",

            "skirt": "Athletic Skirt",
            "sports bra": "Sports Bra",
            "workout top": "Workout Top",
            "yoga pants": "Yoga Pants",
            "yoga trousers": "Yoga Pants",
            "yoga leggings": "Yoga Pants",
            "legging": "Workout Leggings",
            "track": "Track Pants",
            "short": "Athletic Shorts",
        },
        "Swimwear": {
            "bikini": "Bikini",
            "one-piece": "One-piece Swimsuit",
            "one piece": "One-piece Swimsuit",
            "cover": "Cover-up",
            "trunk": "Swim Trunks",
        },
        "Intimates": {
            "pantyhose": "Tights",
            "tights": "Tights",
            "bra": "Bra",
            "underwear": "Underwear",
            "lounge": "Loungewear",
            "pajama": "Pajamas",
            "slip": "Slip",
        },
    }

    for needle, target in mappings.get(category, {}).items():
        if needle in lowered:
            return target
    return None
