from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

from app.core.constants import (
    DEFAULT_CATEGORY,
    DEFAULT_COLOR,
    DEFAULT_OCCASION,
    DEFAULT_SEASON,
    DEFAULT_STYLE,
    FORMALITY_SCORE_MAX,
    FORMALITY_SCORE_MIN,
    MODEL_CONFIDENCE_MAX,
    MODEL_CONFIDENCE_MIN,
    OPENAI_RESPONSES_URL,
    OPENAI_VISION_TIMEOUT_SECONDS,
    WARMTH_LEVEL_MAX,
    WARMTH_LEVEL_MIN,
    RecognitionSource,
)
from app.core.config import settings
from app.models.domain import ClothingAnalysis
from app.services.taxonomy import CATEGORIES, COLORS, OCCASIONS, SEASONS, STYLES, constrain_category, normalize_subtype


class ClothingRecognitionService:
    def analyze(
        self,
        filename: str,
        image_url: str | None = None,
        allowed_categories: list[str] | None = None,
        user_profile: dict[str, Any] | None = None,
    ) -> ClothingAnalysis:
        can_use_vision, reason = self._openai_vision_status(image_url)
        print(f"RECOGNITION PIPELINE: OpenAI Vision available={can_use_vision}. {reason}")

        if can_use_vision:
            try:
                return self._analyze_with_openai_vision(
                    image_url=image_url or "",
                    allowed_categories=allowed_categories,
                    user_profile=user_profile,
                )
            except Exception as error:
                print("OPENAI VISION RECOGNITION FAILED:", error)

        return self._analyze_with_heuristics(filename, allowed_categories=allowed_categories)

    def _can_use_openai_vision(self, image_url: str | None) -> bool:
        return self._openai_vision_status(image_url)[0]

    def _openai_vision_status(self, image_url: str | None) -> tuple[bool, str]:
        if not settings.openai_api_key:
            return False, "OPENAI_API_KEY is missing."
        if not image_url:
            return False, "Image URL is missing."
        if not image_url.startswith("https://"):
            return False, f"Image URL is not public HTTPS: {image_url}"
        if "localhost" in image_url or "127.0.0.1" in image_url:
            return False, f"Image URL is local-only: {image_url}"
        return True, f"Using model={settings.openai_vision_model}, detail={settings.openai_vision_detail}."

    def _analyze_with_openai_vision(
        self,
        image_url: str,
        allowed_categories: list[str] | None = None,
        user_profile: dict[str, Any] | None = None,
    ) -> ClothingAnalysis:
        response = httpx.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_vision_model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": self._vision_prompt(allowed_categories=allowed_categories, user_profile=user_profile),
                            },
                            {
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": settings.openai_vision_detail,
                            },
                        ],
                    }
                ],
            },
            timeout=OPENAI_VISION_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        parsed = self._parse_response_text(payload)
        return self._normalize_model_payload(parsed, raw_response=payload, allowed_categories=allowed_categories)

    def _parse_response_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = payload.get("output_text")
        if not text:
            chunks: list[str] = []
            for output_item in payload.get("output", []):
                for content_item in output_item.get("content", []):
                    if content_item.get("type") in {"output_text", "text"} and content_item.get("text"):
                        chunks.append(content_item["text"])
            text = "\n".join(chunks)

        if not text:
            raise ValueError("OpenAI vision response did not include output text.")

        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        return json.loads(cleaned)

    def _normalize_model_payload(
        self,
        parsed: dict[str, Any],
        raw_response: dict[str, Any],
        allowed_categories: list[str] | None = None,
    ) -> ClothingAnalysis:
        raw_category = str(parsed.get("category") or DEFAULT_CATEGORY)
        raw_subtype = parsed.get("subtype") or parsed.get("type")
        raw_color = str(parsed.get("color") or DEFAULT_COLOR)
        raw_style = str(parsed.get("style") or DEFAULT_STYLE)
        raw_occasion = str(parsed.get("occasion") or DEFAULT_OCCASION)
        raw_seasons = parsed.get("seasons") or parsed.get("season") or [DEFAULT_SEASON]

        if isinstance(raw_seasons, str):
            raw_seasons = [raw_seasons]
        if not isinstance(raw_seasons, list):
            raw_seasons = [DEFAULT_SEASON]

        category = self._normalize_category(raw_category, raw_subtype, allowed_categories=allowed_categories)
        subtype = normalize_subtype(category, str(raw_subtype) if raw_subtype else None)
        color = self._normalize_color(raw_color)
        style = self._normalize_style(raw_style)
        occasion = self._normalize_occasion(raw_occasion)
        seasons = self._normalize_seasons([str(season) for season in raw_seasons])
        confidence = parsed.get("confidence")

        return ClothingAnalysis(
            category=category,
            subtype=subtype,
            color=color,
            seasons=seasons,
            style=style,
            occasion=occasion,
            material=self._string_or_none(parsed.get("material")),
            pattern=self._string_or_none(parsed.get("pattern")),
            fit=self._string_or_none(parsed.get("fit")),
            length=self._string_or_none(parsed.get("length")),
            sleeve_length=self._string_or_none(parsed.get("sleeve_length")),
            neckline=self._string_or_none(parsed.get("neckline")),
            layering_role=self._string_or_none(parsed.get("layering_role")),
            warmth_level=self._bounded_int(parsed.get("warmth_level"), minimum=WARMTH_LEVEL_MIN, maximum=WARMTH_LEVEL_MAX),
            formality_score=self._bounded_int(parsed.get("formality_score"), minimum=FORMALITY_SCORE_MIN, maximum=FORMALITY_SCORE_MAX),
            confidence=float(confidence) if isinstance(confidence, int | float) else None,
            summary=str(parsed.get("notes") or parsed.get("summary") or "").strip() or None,
            source=RecognitionSource.OPENAI_VISION,
            raw_category=raw_category,
            raw_subtype=str(raw_subtype) if raw_subtype else None,
            raw_color=raw_color,
            raw_style=raw_style,
            raw_occasion=raw_occasion,
            raw_seasons=[str(season) for season in raw_seasons],
        )

    def _analyze_with_heuristics(self, filename: str, allowed_categories: list[str] | None = None) -> ClothingAnalysis:
        tokens = re.split(r"[^a-z0-9]+", Path(filename).stem.lower())
        haystack = " ".join(tokens)

        category = constrain_category(self._category_from_tokens(haystack), haystack, allowed_categories)
        subtype = normalize_subtype(category, haystack)
        color = self._color_from_tokens(tokens)
        style = self._style_from_tokens(tokens)
        occasion = self._occasion_from_tokens(tokens)
        seasons = self._season_from_tokens(tokens)

        return ClothingAnalysis(
            category=category,
            subtype=subtype,
            color=color,
            seasons=seasons,
            style=style,
            occasion=occasion,
            material=None,
            pattern=None,
            fit=None,
            length=None,
            sleeve_length=None,
            neckline=None,
            layering_role=self._layering_role(category),
            warmth_level=self._warmth_level(category, subtype),
            formality_score=self._formality_score(style, occasion),
            confidence=0.42 if tokens else None,
            summary=self._summary(category, subtype, color, style),
            source=RecognitionSource.HEURISTIC_FALLBACK,
            raw_category=category,
            raw_subtype=subtype,
            raw_color=color,
            raw_style=style,
            raw_occasion=occasion,
            raw_seasons=seasons,
        )

    def _vision_prompt(self, allowed_categories: list[str] | None = None, user_profile: dict[str, Any] | None = None) -> str:
        categories = allowed_categories or CATEGORIES
        profile_note = ""
        if user_profile:
            daily_occasions = user_profile.get("daily_occasions") or []
            style_preferences = user_profile.get("style_preferences") or []
            profile_note = (
                "\nUser profile context for interpretation only: "
                f"daily occasions={daily_occasions}; preferred styles={style_preferences}."
            )
        return f"""
Analyze the main clothing item in this image. Return only valid JSON with these keys:
category, subtype, color, seasons, style, occasion, material, pattern, fit, length, sleeve_length, neckline, layering_role, warmth_level, formality_score, confidence, notes.

Rules:
- category must be one of: {", ".join(categories)}
- color must be one of: {", ".join(COLORS)}
- seasons must be an array using only: {", ".join(SEASONS)}
- style must be one of: {", ".join(STYLES)}
- occasion must be one of: {", ".join(OCCASIONS)}
- material should be a concise fabric or material label when visible, otherwise null
- pattern should be a concise pattern label such as Solid, Floral, Striped, Graphic, Plaid, Denim, Lace, or null
- fit should be one of Slim, Regular, Relaxed, Oversized, Bodycon, Tailored, or null
- length should be one of Cropped, Hip, Thigh, Knee, Midi, Maxi, Full, or null
- sleeve_length should be one of Sleeveless, Short Sleeve, Long Sleeve, Strapless, Spaghetti Strap, or null
- neckline should be one of Crew, V-neck, Scoop, Square, Collar, Turtleneck, Sweetheart, Halter, Off-shoulder, or null
- layering_role should be one of Base Layer, Mid Layer, Outer Layer, Standalone, Footwear, Accessory, or null
- warmth_level must be an integer from {WARMTH_LEVEL_MIN} to {WARMTH_LEVEL_MAX} where {WARMTH_LEVEL_MIN} is very light and {WARMTH_LEVEL_MAX} is very warm
- formality_score must be an integer from {FORMALITY_SCORE_MIN} to {FORMALITY_SCORE_MAX} where {FORMALITY_SCORE_MIN} is casual and {FORMALITY_SCORE_MAX} is formal
- confidence must be a number from {MODEL_CONFIDENCE_MIN} to {MODEL_CONFIDENCE_MAX}
- notes must be one short sentence
Focus on the garment, not the person, room, mirror, face, or background.
{profile_note}
""".strip()

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

    def _normalize_color(self, color: str) -> str:
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
            "green": "Green",
            "olive": "Green",
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
                return value
        return color if color in COLORS else "Unknown"

    def _normalize_style(self, style: str) -> str:
        normalized = style.lower().strip()
        if normalized in {"formal", "elegant"}:
            return "Formal" if normalized == "formal" else "Elegant"
        if normalized in {"business", "business casual", "office"}:
            return "Business"
        if normalized in {"sporty", "athleisure"}:
            return "Sporty"
        if normalized == "streetwear":
            return "Streetwear"
        if normalized in {"minimal", "minimalist"}:
            return "Minimalist"
        if normalized in {"romantic", "feminine"}:
            return "Romantic"
        if normalized in {"classic", "timeless", "chic"}:
            return "Classic"
        if normalized in {"bohemian", "boho"}:
            return "Bohemian"
        if normalized == "preppy":
            return "Preppy"
        if normalized in {"edgy", "punk"}:
            return "Edgy"
        return style if style in STYLES else DEFAULT_STYLE

    def _normalize_occasion(self, occasion: str) -> str:
        normalized = occasion.lower().strip()
        if normalized in {"work", "office", "business"}:
            return "Work"
        if normalized in {"party", "night out"}:
            return "Party"
        if normalized in {"date", "date night"}:
            return "Date"
        if normalized == "travel":
            return "Travel"
        if normalized in {"vacation", "beach", "resort"}:
            return "Vacation"
        if normalized in {"workout", "gym", "sport"}:
            return "Workout"
        if normalized in {"wedding", "formal event"}:
            return "Wedding"
        if normalized in {"lounge", "home"}:
            return "Lounge"
        if normalized in {"evening", "gala"}:
            return "Evening"
        return occasion if occasion in OCCASIONS else DEFAULT_OCCASION

    def _normalize_seasons(self, seasons: list[str]) -> list[str]:
        mapped: list[str] = []
        season_map = {
            "spring": "Spring",
            "summer": "Summer",
            "fall": "Fall",
            "autumn": "Fall",
            "winter": "Winter",
            "all-season": DEFAULT_SEASON,
            "all season": DEFAULT_SEASON,
            "year-round": DEFAULT_SEASON,
            "year round": DEFAULT_SEASON,
        }
        for season in seasons:
            value = season_map.get(season.lower().strip())
            if value and value not in mapped:
                mapped.append(value)
        return mapped or [DEFAULT_SEASON]

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
        if any(word in haystack for word in ["jacket", "coat", "blazer", "puffer", "windbreaker", "trench", "outerwear"]):
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
