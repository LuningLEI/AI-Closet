from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from app.ai.gateway import AIGateway, build_ai_gateway

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
    OPENAI_VISION_TIMEOUT_SECONDS,
    WARMTH_LEVEL_MAX,
    WARMTH_LEVEL_MIN,
    RecognitionSource,
)
from app.core.config import settings
from app.models.domain import ClothingAnalysis
from app.services.occasion_support import select_scored_occasions
from app.services.recognition_normalization import RecognitionNormalizationMixin
from app.services.taxonomy import SUBTYPES, CATEGORIES, COLORS, OCCASIONS, SEASONS, STYLES, LENGTHS, SLEEVE_LENGTHS, constrain_category, normalize_subtype


class ClothingRecognitionService(RecognitionNormalizationMixin):
    def __init__(self, occasion_threshold: float | None = None, gateway: AIGateway | None = None) -> None:
        self.occasion_threshold = settings.recognition_occasion_threshold if occasion_threshold is None else occasion_threshold
        self.gateway = gateway or build_ai_gateway()
        if not math.isfinite(self.occasion_threshold) or not 0 <= self.occasion_threshold <= 1:
            raise ValueError("Occasion threshold must be between 0 and 1.")

    def analyze(
        self,
        filename: str,
        image_url: str | None = None,
        allowed_categories: list[str] | None = None,
        user_profile: dict[str, Any] | None = None,
        allowed_taxonomy: dict[str,Any] | None = None,
    ) -> ClothingAnalysis:
        can_use_vision, reason = self._openai_vision_status(image_url)
        if not can_use_vision:
            raise RuntimeError(reason)
        # Fail into the durable queue; filename heuristics are not successful vision.
        return self._analyze_with_openai_vision(
            image_url=image_url or "", allowed_categories=allowed_categories,
            user_profile=user_profile,allowed_taxonomy=allowed_taxonomy,
        )

    def _can_use_openai_vision(self, image_url: str | None) -> bool:
        return self._openai_vision_status(image_url)[0]

    def _openai_vision_status(self, image_url: str | None) -> tuple[bool, str]:
        if not settings.ai_api_key:
            return False, "AI_API_KEY is missing."
        if not image_url:
            return False, "Image URL is missing."
        if not image_url.startswith("https://"):
            return False, "Image URL is not public HTTPS."
        if "localhost" in image_url or "127.0.0.1" in image_url:
            return False, "Image URL is local-only."
        return True, f"Using model={settings.openai_vision_model}, detail={settings.openai_vision_detail}."

    def _analyze_with_openai_vision(
        self,
        image_url: str,
        allowed_categories: list[str] | None = None,
        user_profile: dict[str, Any] | None = None,
        allowed_taxonomy: dict[str,Any] | None = None,
    ) -> ClothingAnalysis:
        result = self.gateway.response(
            model=settings.openai_vision_model,
            input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": self._vision_prompt(allowed_categories=allowed_categories, user_profile=user_profile,
                                                            allowed_taxonomy=allowed_taxonomy),
                            },
                            {
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": settings.openai_vision_detail,
                            },
                        ],
                    }
                ],
            timeout=OPENAI_VISION_TIMEOUT_SECONDS,
        )
        payload = result.payload
        parsed = self._parse_response_text(payload)
        return self._normalize_model_payload(parsed, raw_response=payload, allowed_categories=allowed_categories,
                                             allowed_taxonomy=allowed_taxonomy)

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
        allowed_taxonomy:dict[str,Any]|None=None,
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
        catalog=allowed_taxonomy or {}
        subtype_options=(catalog.get('subtypes') or {}).get(category,SUBTYPES.get(category,['Unknown']))
        subtype=(str(raw_subtype) if raw_subtype in subtype_options else normalize_subtype(category,str(raw_subtype) if raw_subtype else None))
        if subtype not in subtype_options:subtype=None
        colors=catalog.get('colors') or COLORS;styles=catalog.get('styles') or STYLES
        occasions=catalog.get('occasions') or OCCASIONS;seasons_allowed=catalog.get('seasons') or SEASONS
        color = self._normalize_color(raw_color,colors)
        style = self._normalize_style(raw_style,styles)
        scores = self._normalize_occasion_scores(parsed.get("occasion_scores"),occasions)
        occasion = (", ".join(select_scored_occasions(
            {entry.occasion: entry.score for entry in scores}, self.occasion_threshold,occasions
        )) if scores else self._normalize_occasion(raw_occasion,occasions))
        seasons = self._normalize_seasons([str(season) for season in raw_seasons],seasons_allowed)
        lengths=catalog.get('lengths') or LENGTHS;sleeve_lengths=catalog.get('sleeve_lengths') or SLEEVE_LENGTHS
        confidence = parsed.get("confidence")
        legacy_length = {'crop top':'Cropped','mini dress':'Thigh','midi dress':'Midi','maxi dress':'Maxi'}.get(str(raw_subtype or '').lower())
        wearing = dict(parsed.get('wearing_profile') or {})

        return ClothingAnalysis(
            category=category,
            subtype=subtype,
            color=color,
            seasons=seasons,
            style=style,
            occasion=occasion,
            occasion_scores=scores,
            occasion_threshold=self.occasion_threshold if scores else None,
            material=self._string_or_none(parsed.get("material")),
            pattern=self._string_or_none(parsed.get("pattern")),
            fit=self._string_or_none(parsed.get("fit")),
            length=(self._string_or_none(parsed.get("length")) if self._string_or_none(parsed.get("length")) in lengths
                    else (legacy_length if legacy_length in lengths else None)),
            sleeve_length=(self._string_or_none(parsed.get("sleeve_length"))
                           if self._string_or_none(parsed.get("sleeve_length")) in sleeve_lengths else None),
            neckline=self._string_or_none(parsed.get("neckline")),
            layering_role=self._string_or_none(parsed.get("layering_role")),
            wearing_profile=wearing,
            color_tones=parsed.get("color_tones") or [],
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

    def _vision_prompt(self, allowed_categories: list[str] | None = None, user_profile: dict[str, Any] | None = None,
                       allowed_taxonomy:dict[str,Any]|None=None) -> str:
        categories = allowed_categories or CATEGORIES
        catalog=allowed_taxonomy or {}
        subtypes=catalog.get('subtypes') or {category:SUBTYPES.get(category,['Unknown']) for category in categories}
        colors=catalog.get('colors') or COLORS;styles=catalog.get('styles') or STYLES
        occasions=catalog.get('occasions') or OCCASIONS;seasons=catalog.get('seasons') or SEASONS
        lengths=catalog.get('lengths') or LENGTHS;sleeve_lengths=catalog.get('sleeve_lengths') or SLEEVE_LENGTHS
        profile_note = ""
        if user_profile:
            daily_occasions = user_profile.get("daily_occasions") or []
            style_preferences = user_profile.get("style_preferences") or []
            occasion_style_preferences = user_profile.get("occasion_style_preferences") or {}
            profile_note = (
                "\nUser profile context for interpretation only: "
                f"daily occasions={daily_occasions}; preferred styles={style_preferences}; "
                f"styles by occasion={occasion_style_preferences}."
            )
        return f"""
Analyze the main clothing item in this image. Return only valid JSON with these keys:
category, subtype, color, color_tones, seasons, style, occasion_scores, material, pattern, fit, length, sleeve_length, neckline, layering_role, wearing_profile, warmth_level, formality_score, confidence, notes.

Rules:
- category must be one of: {", ".join(categories)}
- subtype must be selected from the category-specific taxonomy: {json.dumps(subtypes)}. Unknown/null is allowed. Crop Top is a length attribute (length=Cropped), not a subtype. Dresses must use construction/silhouette types, with hem length stored separately. Playsuit maps to Romper; Matching/Co-ord sets map to Two-piece Set; Pumps maps to Heels. Cardigan belongs to Outerwear; determine its wearing capabilities from the image rather than forcing requirements from its subtype.
- color_tones must be an array, one entry per identifiable garment color tag: color (matching the color tag), hue (HSL hue 0–360 or null for achromatic/uncertain colors), saturation (0–1 or null), lightness (0–1 or null), evidence (short visual basis or null). Lightness 0 is black, 1 is white; saturation 0 is muted/gray, 1 vivid. Estimate garment fabric only, excluding background, hanger, glare and shadow. These are photo-based estimates, not calibrated physical measurements. Use null when lighting makes a component uncertain; do not invent one constant value for all pink garments.
- color must be a comma-separated string of one or more distinct labels from: {", ".join(colors)}. Include the visible garment colors, excluding background and hanger colors. Use Unknown only when no color can be identified.
- seasons must be an array of one or more seasons. For year-round garments select every available season; never output All-Season. Use only: {", ".join(seasons)}
- style must be one of: {", ".join(styles)}
- occasion_scores must be an array with exactly one object per label: {", ".join(occasions)}
- Each object has "occasion" (the exact label) and "score" (a number from 0 to 1).
- Score each occasion independently for garment suitability: 0 is unsuitable, 1 is strongly suitable. Multiple occasions can score highly; scores need not sum to 1. Return every score, including low scores.
- Do not bias occasion scores toward the user profile or apply a threshold.
- Choose category by garment construction and intended function BEFORE choosing its silhouette. Activewear includes both upper and lower garments: do not default to Tops or Bottoms merely because the item looks like a T-shirt, tank, fitted pants or wide-leg pants. Sporty style and Workout occasion alone do not establish Activewear.
- Compare exercise construction against ordinary casual construction: a broad stretch waistband, gusset/panel seams, flatlock seams and smooth stretch fabric support yoga/exercise pants; a fly, belt loops, tailored creases and woven drape support ordinary trousers. Weigh multiple visible cues, not black color or leg width alone. Fabric composition and stretch cannot be known with certainty from a photo; do not invent them.
- For exercise tops, inspect technical fabric appearance, mesh ventilation, flatlock/panel seams, supportive construction and performance cut together. Choose Activewear / Workout Top for athletic tanks, short-sleeved training shirts and long-sleeved workout tops; record sleeve_length separately. Choose Sports Bra for a supportive exercise bra, and Athletic Jacket for an athletic zip jacket. A plain cotton T-shirt, ordinary camisole or casual hoodie remains Tops unless exercise-specific construction is supported. A yoga top is Workout Top, never Yoga Pants.
- Before returning JSON, check category/subtype consistency and explicitly compare Activewear with Tops/Bottoms for plausible exercise garments. If ambiguous, explain the uncertainty in notes rather than treating the generic silhouette as proof of casual use. User lifestyle preferences must not override visible construction.
- For ski garments use category Activewear and subtype Ski Jacket, Ski Pants, or Ski Suit. Ski Suit means a one-piece garment, not separate jacket and pants.
- For general exercise/running leggings, use category Activewear and subtype Workout Leggings, not Bottoms/Leggings.
- For yoga pants use Activewear / Yoga Pants, whether fitted, straight, flared or wide-leg. Evaluate the stretch waistband, athletic construction, seams and fabric appearance together; wide legs alone do not imply ordinary Bottoms / Wide-leg Pants, and narrow legs alone do not imply Joggers. Do not infer yoga use from black color alone. If the purpose is not visually supported, do not invent it; preserve uncertainty in notes.
- Record yoga pant silhouette independently in fit: Skinny for close-fitting legs, Straight-leg, Flared or Wide-leg. Yoga Pants describes purpose, not leg width.
- Vest exists in both Tops and Outerwear. Choose Outerwear / Vest for outer vests such as padded/puffer vests, fleece gilets and sleeveless outer jackets; choose Tops / Vest for sweater vests or tailored vests functioning as tops. Judge wearing capabilities independently from visible construction, not from the category name alone.
- For fitted athletic zip-front jackets (such as a Define-style jacket), use category Activewear and subtype Athletic Jacket; use fit Slim when supported by the image. Do not infer a brand from appearance alone.
- material should be a concise fabric or material label when visible, otherwise null
- pattern should be a concise pattern label such as Solid, Floral, Striped, Graphic, Plaid, Denim, Lace, or null
- fit should be one of Slim, Regular, Relaxed, Oversized, Bodycon, Tailored, Skinny, Straight-leg, Flared, Wide-leg, or null
- length should be one of {", ".join(lengths)}, or null
- sleeve_length should be one of {", ".join(sleeve_lengths)}, or null
- neckline should be one of Crew, V-neck, Scoop, Square, Collar, Turtleneck, Sweetheart, Halter, Off-shoulder, or null
- layering_role should be one of Base Layer, Mid Layer, Outer Layer, Standalone, Footwear, Accessory, or null
- wearing_profile must be an object with layering_region, lower_layer_role, can_wear_alone, can_layer_over, can_layer_under, requires_inner_layer, closure_type, layering_bulk, outer_capacity, material_stiffness, hood_volume, sleeve_volume, wearing_modes, evidence.
- The four capability fields must be true, false, or null (unknown/not applicable). They concern layering on the garment's body region, not the need for complementary upper/lower garments, shoes or ordinary underwear. For Tights/pantyhose use layering_region=lower_body, lower_layer_role=base, can_wear_alone=false; judge can_layer_under from the image. They are hosiery, never a standalone bottom, and pair only under a skirt, dress or shorts, not trousers or leggings. Their Intimates category stays unchanged. For shoes and other accessories use null capabilities and no wearing modes; closure_type may still be identified.
- layering_region is upper_body, lower_body, full_body, or null. lower_layer_role is base, outer, or null: close-fitting leggings can be a lower base when fabric and fit permit; a suitably roomy skirt/shorts can be a lower outer layer. Do not automatically grant every pair of pants a layering role. Wide-leg or flared Yoga Pants are not close-fitting lower base layers: use can_layer_under=false and lower_layer_role=null unless specific construction provides evidence otherwise. Dresses may have lower_layer_role=outer only if the skirt portion can accommodate a lower base; jumpsuits are not automatically lower outer layers.
- can_wear_alone means this garment can cover its body region without another garment on that region. For lower-body garments, can_layer_under and can_layer_over refer to lower-body layers, not upper tops. requires_inner_layer=true fixes the required layer INSIDE; can_wear_alone=false may instead be satisfied by an outside covering layer. can_layer_over means it can fit over another garment on the same body region, NOT merely that it is suitable to be visible outdoors. can_layer_under means it fits as an inner garment. requires_inner_layer means another inner garment on the same body region is necessary for coverage or the garment's construction.
- Inspect opacity, coverage, armholes, neckline, fit, thickness and opening. Do not assume every top can be worn alone or layered. Do not assume all vests require an inner layer: a suit vest may support standalone wear, while a sweater/puffer vest may need one. A sheer garment may require coverage underneath. A shirt may support standalone wear and open layering over a tank when its construction and fit permit.
- closure_type must be pullover, buttons, zipper, open_front, wrap, other, or null. Never infer hidden closures confidently.
- layering_bulk describes the garment's volume when worn under another upper-body garment: low, medium, high, or null. Hoodies, chunky knits, oversized torsos and voluminous sleeves increase bulk; do not mark every sweater high.
- outer_capacity describes visible room for another upper-body garment underneath: low, medium, high, or null. Inspect shoulder, armhole, sleeve and torso room. A generic can_layer_over=true does not imply high capacity.
- material_stiffness must be soft, medium, stiff, or null. Denim, rigid leather and structured twill are often stiff; knit and stretch jersey are often soft, but use visible evidence and preserve uncertainty.
- hood_volume must be none, low, high, or null. A substantial hoodie hood can conflict with a close-necked or fitted outer layer.
- sleeve_volume must be slim, regular, voluminous, or null. Balloon, bishop, puff and visibly wide sleeves are voluminous.
- can_wear_alone=false does NOT imply requires_inner_layer=true. A sheer top may be unsuitable alone but work either over an opaque tank OR under a short-sleeved T-shirt with sheer sleeves visible. In that case requires_inner_layer=false, with can_layer_over/can_layer_under determined independently. False means no such directional requirement; null means unknown. can_layer_over is a capability, not an obligation to add an inner garment. Assess opacity/coverage of the combined garments during outfit review.
- wearing_modes must contain only visually supported modes from standalone, inner_layer, outer_layer_closed, outer_layer_open. Return [] if unknown/not applicable. A pullover cannot have outer_layer_open. If requires_inner_layer is true, do not allow standalone. Do not list modes contradicted by a false capability.
- evidence is a concise image-grounded reason, or null if not applicable. Unknown is not false; do not invent measurements or certainty from the category name alone.
- warmth_level must be an integer from {WARMTH_LEVEL_MIN} to {WARMTH_LEVEL_MAX} where {WARMTH_LEVEL_MIN} is very light and {WARMTH_LEVEL_MAX} is very warm
- formality_score must be an integer from {FORMALITY_SCORE_MIN} to {FORMALITY_SCORE_MAX} where {FORMALITY_SCORE_MIN} is casual and {FORMALITY_SCORE_MAX} is formal
- confidence must be a number from {MODEL_CONFIDENCE_MIN} to {MODEL_CONFIDENCE_MAX}
- notes must be one short sentence
Focus on the garment, not the person, room, mirror, face, or background.
{profile_note}
""".strip()
