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
OCCASIONS = ["Everyday", "Work", "Party", "Date", "Travel", "Workout", "Wedding", "Vacation", "Lounge", "Evening"]
SEASONS = ["All-Season", "Spring", "Summer", "Fall", "Winter"]

SUBTYPES = {
    "Tops": [
        "Unknown",
        "T-shirt",
        "Tank Top",
        "Camisole",
        "Blouse",
        "Button-down Shirt",
        "Sweater",
        "Hoodie",
        "Cardigan",
        "Pullover",
        "Crop Top",
        "Bodysuit",
        "Vest",
    ],
    "Bottoms": [
        "Unknown",
        "Jeans",
        "Wide-leg Pants",
        "Straight-leg Pants",
        "Trousers",
        "Leggings",
        "Joggers",
        "Shorts",
        "Mini Skirt",
        "Midi Skirt",
        "Maxi Skirt",
    ],
    "Dresses": [
        "Unknown",
        "Slip Dress",
        "Mini Dress",
        "Midi Dress",
        "Maxi Dress",
        "Bodycon Dress",
        "Shirt Dress",
        "Wrap Dress",
        "Sundress",
        "Gown",
    ],
    "Jumpsuits": ["Unknown", "Jumpsuit", "Romper", "Playsuit"],
    "Sets": ["Unknown", "Two-piece Set", "Suit Set", "Matching Set", "Co-ord Set"],
    "Outerwear": ["Unknown", "Jacket", "Coat", "Blazer", "Cardigan", "Puffer", "Windbreaker", "Trench Coat", "Leather Jacket"],
    "Shoes": ["Unknown", "Sneakers", "Boots", "Sandals", "Heels", "Pumps", "Loafers", "Flats", "Mules", "Slippers"],
    "Bags": ["Unknown", "Tote", "Shoulder Bag", "Crossbody Bag", "Clutch", "Backpack", "Mini Bag"],
    "Accessories": ["Unknown", "Hat", "Scarf", "Belt", "Jewelry", "Watch", "Sunglasses", "Hair Accessory"],
    "Activewear": ["Unknown", "Sports Bra", "Workout Top", "Workout Leggings", "Track Pants", "Athletic Shorts"],
    "Swimwear": ["Unknown", "Bikini", "One-piece Swimsuit", "Cover-up", "Swim Trunks"],
    "Intimates": ["Unknown", "Bra", "Underwear", "Loungewear", "Pajamas", "Slip"],
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
        },
        "taxonomy": {
            "selected_categories": CATEGORIES,
            "custom_categories": [],
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
    if "onboarding_completed" in preferences:
        merged["onboarding_completed"] = bool(preferences["onboarding_completed"])
    return merged


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


def user_subtypes(categories: list[str]) -> dict[str, list[str]]:
    return {category: SUBTYPES.get(category, ["Unknown"]) for category in categories}


def constrain_category(category: str, subtype: Any, allowed_categories: list[str] | None = None) -> str:
    allowed = allowed_categories or CATEGORIES
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
        ("Outerwear", ["outerwear", "jacket", "coat", "blazer", "cardigan", "puffer", "trench"]),
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
    if subtype in options:
        return None if subtype == "Unknown" else subtype

    lowered = subtype.lower()
    mappings = {
        "Tops": {
            "tee": "T-shirt",
            "t-shirt": "T-shirt",
            "tank": "Tank Top",
            "cami": "Camisole",
            "blouse": "Blouse",
            "button": "Button-down Shirt",
            "shirt": "Button-down Shirt",
            "sweater": "Sweater",
            "hoodie": "Hoodie",
            "cardigan": "Cardigan",
            "pullover": "Pullover",
            "crop": "Crop Top",
            "bodysuit": "Bodysuit",
            "vest": "Vest",
        },
        "Bottoms": {
            "wide": "Wide-leg Pants",
            "straight": "Straight-leg Pants",
            "jean": "Jeans",
            "trouser": "Trousers",
            "pant": "Trousers",
            "legging": "Leggings",
            "jogger": "Joggers",
            "short": "Shorts",
            "mini skirt": "Mini Skirt",
            "midi skirt": "Midi Skirt",
            "maxi skirt": "Maxi Skirt",
            "skirt": "Midi Skirt",
        },
        "Dresses": {
            "slip": "Slip Dress",
            "mini": "Mini Dress",
            "midi": "Midi Dress",
            "maxi": "Maxi Dress",
            "bodycon": "Bodycon Dress",
            "shirt": "Shirt Dress",
            "wrap": "Wrap Dress",
            "sun": "Sundress",
            "gown": "Gown",
            "dress": "Unknown",
        },
        "Jumpsuits": {
            "jumpsuit": "Jumpsuit",
            "romper": "Romper",
            "playsuit": "Playsuit",
        },
        "Sets": {
            "two-piece": "Two-piece Set",
            "two piece": "Two-piece Set",
            "suit": "Suit Set",
            "matching": "Matching Set",
            "coord": "Co-ord Set",
            "co-ord": "Co-ord Set",
        },
        "Shoes": {
            "sneaker": "Sneakers",
            "boot": "Boots",
            "sandal": "Sandals",
            "heel": "Heels",
            "pump": "Pumps",
            "loafer": "Loafers",
            "flat": "Flats",
            "mule": "Mules",
            "slipper": "Slippers",
        },
        "Outerwear": {
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
            "sports bra": "Sports Bra",
            "workout top": "Workout Top",
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
