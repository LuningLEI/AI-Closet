"""Catalog normalization helpers shared by recognition providers."""
from __future__ import annotations

import math
from typing import Any

from app.core.constants import DEFAULT_CATEGORY, DEFAULT_OCCASION, DEFAULT_STYLE
from app.models.domain import OccasionScore
from app.services.taxonomy import COLORS, OCCASIONS, SEASONS, STYLES, constrain_category


class RecognitionNormalizationMixin:
    def _string_or_none(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _bounded_int(self, value: Any, minimum: int, maximum: int) -> int | None:
        if value is None:
            return None
        try:
            number = int(round(float(value)))
        except (TypeError, ValueError):
            return None
        return max(minimum, min(maximum, number))

    def _layering_role(self, category: str) -> str | None:
        if category == "Outerwear":
            return "Outer Layer"
        if category in {"Tops", "Activewear", "Intimates"}:
            return "Base Layer"
        if category in {"Dresses", "Jumpsuits", "Sets", "Swimwear"}:
            return "Standalone"
        if category == "Shoes":
            return "Footwear"
        if category in {"Bags", "Accessories"}:
            return "Accessory"
        return None

    def _warmth_level(self, category: str, subtype: str | None) -> int | None:
        subtype_text = (subtype or "").lower()
        if category == "Outerwear" or any(word in subtype_text for word in ["coat", "puffer", "sweater", "hoodie"]):
            return 4
        if any(word in subtype_text for word in ["tank", "cami", "shorts", "swim"]):
            return 1
        if category in {"Tops", "Bottoms", "Dresses", "Jumpsuits", "Sets"}:
            return 2
        return None

    def _formality_score(self, style: str, occasion: str) -> int | None:
        if style in {"Formal", "Elegant"} or occasion in {"Wedding", "Evening"}:
            return 5
        if style == "Business" or occasion == "Work":
            return 4
        if style in {"Classic", "Preppy"}:
            return 3
        if style in {"Casual", "Sporty", "Streetwear"}:
            return 2
        return None

    def _normalize_category(self, category: str, subtype: Any, allowed_categories: list[str] | None = None) -> str:
        return constrain_category(category, subtype, allowed_categories)

    def _normalize_color(self, color: str, allowed: list[str] = COLORS) -> str:
        if "," in color:
            colors = list(dict.fromkeys(self._normalize_color(part.strip(),allowed) for part in color.split(",") if part.strip()))
            known = [value for value in colors if value != "Unknown"]
            return ", ".join(known) if known else "Unknown"
        normalized = color.lower().strip()
        color_map = {
            "black": "Black",
            "charcoal": "Black",
            "white": "White",
            "ivory": "White",
            "cream": "White",
            "gray": "Gray",
            "grey": "Gray",
            "silver": "Silver",
            "blue": "Blue",
            "denim": "Blue",
            "navy": "Navy",
            "red": "Red",
            "burgundy": "Red",
            "olive": "Olive",
            "green": "Green",
            "brown": "Brown",
            "tan": "Brown",
            "beige": "Beige",
            "pink": "Pink",
            "purple": "Purple",
            "yellow": "Yellow",
            "orange": "Orange",
            "gold": "Gold",
            "multi": "Multicolor",
        }
        for needle, value in color_map.items():
            if needle in normalized:
                return value if value in allowed else "Unknown"
        return color if color in allowed else "Unknown"

    def _normalize_style(self, style: str, allowed: list[str] = STYLES) -> str:
        if style in allowed:return style
        normalized = style.lower().strip()
        mapped=None
        if normalized in {"formal", "elegant"}:
            mapped="Formal" if normalized == "formal" else "Elegant"
        elif normalized in {"business", "business casual", "office"}:mapped="Business"
        elif normalized in {"sporty", "athleisure"}:mapped="Sporty"
        elif normalized == "streetwear":mapped="Streetwear"
        elif normalized in {"minimal", "minimalist"}:mapped="Minimalist"
        elif normalized in {"romantic", "feminine"}:mapped="Romantic"
        elif normalized in {"classic", "timeless", "chic"}:mapped="Classic"
        elif normalized in {"bohemian", "boho"}:mapped="Bohemian"
        elif normalized == "preppy":mapped="Preppy"
        elif normalized in {"edgy", "punk"}:mapped="Edgy"
        return mapped if mapped in allowed else allowed[0]

    def _normalize_occasion_scores(self, value: Any, allowed: list[str] = OCCASIONS) -> list[OccasionScore]:
        if not isinstance(value, list):
            return []
        valid: dict[str, float] = {}
        labels = {label.lower(): label for label in allowed}
        if "Travel" in allowed:labels["vacation"] = "Travel"
        for entry in value:
            if not isinstance(entry, dict) or not isinstance(entry.get("occasion"), str):
                continue
            label = labels.get(entry["occasion"].strip().lower())
            score = entry.get("score")
            if label is None or isinstance(score, bool) or not isinstance(score, (int, float)):
                continue
            if not math.isfinite(score) or not 0 <= score <= 1:
                continue
            valid[label] = max(valid.get(label, 0), score)
        return [OccasionScore(occasion=label, score=score) for label, score in
                sorted(valid.items(), key=lambda entry: (-entry[1], allowed.index(entry[0])))]

    def _normalize_occasion(self, occasion: str, allowed: list[str] = OCCASIONS) -> str:
        if occasion in allowed:return occasion
        normalized = occasion.lower().strip()
        mapped=None
        if normalized in {"work", "office", "business"}:
            mapped="Work"
        elif normalized in {"party", "night out"}:mapped="Party"
        elif normalized in {"date", "date night"}:mapped="Date"
        elif normalized in {"travel","vacation", "beach", "resort"}:mapped="Travel"
        elif normalized in {"workout", "gym", "sport"}:mapped="Workout"
        elif normalized in {"wedding", "formal event"}:mapped="Wedding"
        elif normalized in {"lounge", "home"}:mapped="Lounge"
        elif normalized in {"evening", "gala"}:mapped="Evening"
        return mapped if mapped in allowed else (DEFAULT_OCCASION if DEFAULT_OCCASION in allowed else allowed[0])

    def _normalize_seasons(self, seasons: list[str], allowed: list[str] = SEASONS) -> list[str]:
        from app.services.season_support import normalize_seasons
        exact=[season for season in allowed if season in seasons]
        if exact:return exact
        return [season for season in normalize_seasons(seasons) if season in allowed] or [allowed[0]]

    def _category_from_tokens(self, haystack: str) -> str:
        if any(word in haystack for word in ["dress", "gown"]):
            return "Dresses"
        if any(word in haystack for word in ["jumpsuit", "romper", "playsuit"]):
            return "Jumpsuits"
        if any(word in haystack for word in ["set", "coord", "co ord", "two piece", "matching"]):
            return "Sets"
        if any(word in haystack for word in ["activewear", "workout", "gym", "athletic"]):
            return "Activewear"
        if any(word in haystack for word in ["swim", "bikini", "swimsuit"]):
            return "Swimwear"
        if any(word in haystack for word in ["bra", "underwear", "pajama", "loungewear"]):
            return "Intimates"
        if any(word in haystack for word in ["bag", "tote", "clutch", "crossbody", "backpack"]):
            return "Bags"
        if any(word in haystack for word in ["sneaker", "shoe", "boot", "sandal", "heel", "loafer", "flat", "slipper"]):
            return "Shoes"
        if any(word in haystack for word in ["cape", "jacket", "coat", "blazer", "puffer", "windbreaker", "trench", "outerwear"]):
            return "Outerwear"
        if any(word in haystack for word in ["hat", "scarf", "belt", "watch", "sunglass", "jewelry"]):
            return "Accessories"
        if any(word in haystack for word in ["jean", "pant", "trouser", "legging", "jogger", "short", "skirt"]):
            return "Bottoms"
        if any(word in haystack for word in ["shirt", "tee", "tshirt", "blouse", "sweater", "hoodie", "cardigan", "pullover", "top"]):
            return "Tops"
        return DEFAULT_CATEGORY

    def _color_from_tokens(self, tokens: list[str]) -> str:
        for token in tokens:
            color = self._normalize_color(token)
            if color != "Unknown":
                return color
        return COLORS[0]

    def _style_from_tokens(self, tokens: list[str]) -> str:
        for token in tokens:
            style = self._normalize_style(token)
            if style != DEFAULT_STYLE or token == "casual":
                return style
        return STYLES[0]

    def _occasion_from_tokens(self, tokens: list[str]) -> str:
        for token in tokens:
            occasion = self._normalize_occasion(token)
            if occasion != DEFAULT_OCCASION or token == "everyday":
                return occasion
        return OCCASIONS[0]

    def _season_from_tokens(self, tokens: list[str]) -> list[str]:
        return self._normalize_seasons(tokens)

    def _summary(self, category: str, subtype: str | None, color: str, style: str) -> str:
        descriptor = subtype or category
        return f"{color} {descriptor.lower()} with a {style.lower()} leaning."
