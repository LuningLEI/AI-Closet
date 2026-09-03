from __future__ import annotations


API_V1_PREFIX = "/api/v1"

DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000001"
PIPELINE_NAME = "web-fastapi-agent-demo"

DEFAULT_CATEGORY = "Uncategorized"
DEFAULT_COLOR = "Unknown"
DEFAULT_SEASON = "All-Season"
DEFAULT_STYLE = "Casual"
DEFAULT_OCCASION = "Everyday"
DEFAULT_TEMPERATURE_F = 68.0
DEFAULT_RECOMMENDATION_LIMIT = 3
TODAY_RECOMMENDATION_LIMIT = 5

MAX_BATCH_UPLOADS = 30
SIGNED_IMAGE_URL_EXPIRES_SECONDS = 900
SIGNED_IMAGE_URL_CACHE_TTL_SECONDS = 300
SIGNED_IMAGE_URL_FAILURE_TTL_SECONDS = 30
VISION_IMAGE_URL_EXPIRES_SECONDS = 3600

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_RESPONSES_TIMEOUT_SECONDS = 20
OPENAI_EMBEDDING_TIMEOUT_SECONDS = 30
OPENAI_VISION_TIMEOUT_SECONDS = 45
WEATHER_HTTP_TIMEOUT_SECONDS = 8
HTTP_NOT_FOUND = 404

DEFAULT_LOCATION_LABEL = "Default weather context"
DEFAULT_LOCATION_LATITUDE = 37.7749
DEFAULT_LOCATION_LONGITUDE = -122.4194

WARMTH_LEVEL_MIN = 1
WARMTH_LEVEL_MAX = 5
FORMALITY_SCORE_MIN = 1
FORMALITY_SCORE_MAX = 5
MODEL_CONFIDENCE_MIN = 0
MODEL_CONFIDENCE_MAX = 1


class RecognitionStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    MANUAL = "manual"
    DEAD_LETTER = "dead_letter"


class RecognitionSource:
    ANALYZING = "Analyzing"
    OPENAI_VISION = "OpenAI Vision"
    HEURISTIC_FALLBACK = "Heuristic Fallback"
    MANUAL_EDIT = "Manual Edit"
    FAILED = "Recognition Failed"


class WeatherSource:
    MANUAL_LOCATION = "manual-location"
    BROWSER_GEOLOCATION = "browser-geolocation"
    IP_GEOLOCATION = "ip-geolocation"
    OPEN_METEO = "open-meteo"
    WEATHER_GOV = "weather.gov"
    FALLBACK = "fallback"


class WeatherCondition:
    CLEAR = "Clear"
    PARTLY_CLOUDY = "Partly cloudy"
    FOGGY = "Foggy"
    RAINY = "Rainy"
    SNOWY = "Snowy"
    STORMY = "Stormy"
    MILD = "Mild"


OPEN_METEO_CLEAR_CODES = {0}
OPEN_METEO_PARTLY_CLOUDY_CODES = {1, 2, 3}
OPEN_METEO_FOG_CODES = {45, 48}
OPEN_METEO_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}
OPEN_METEO_SNOW_CODES = {71, 73, 75, 77, 85, 86}
OPEN_METEO_STORM_CODES = {95, 96, 99}


class LayeringRole:
    BASE_TOP = "base_top"
    TOP = "top"
    MID_LAYER = "mid_layer"
    FULL_BODY = "FullBody"
    ACCESSORIES = "Accessories"


RECOGNITION_IN_PROGRESS_SOURCES = {RecognitionSource.ANALYZING}
RECOGNITION_EXCLUDED_SOURCES = {RecognitionSource.ANALYZING, RecognitionSource.FAILED}
RETRYABLE_JOB_STATUSES = {RecognitionStatus.QUEUED, RecognitionStatus.FAILED}
TERMINAL_JOB_STATUS = RecognitionStatus.COMPLETE

CORE_STYLE_VECTOR_LABELS = ["Casual", "Formal", "Business", "Sporty", "Streetwear", "Elegant", "Minimalist"]
CORE_CATEGORY_VECTOR_LABELS = ["Upper", "Lower", "Full-body", "Shoes", "Outerwear", "Accessories"]
CATEGORY_VECTOR_GROUPS = {
    "Tops": "Upper",
    "Activewear": "Upper",
    "Intimates": "Upper",
    "Bottoms": "Lower",
    "Dresses": "Full-body",
    "Jumpsuits": "Full-body",
    "Sets": "Full-body",
    "Shoes": "Shoes",
    "Outerwear": "Outerwear",
    "Bags": "Accessories",
    "Accessories": "Accessories",
    "Swimwear": "Full-body",
    DEFAULT_CATEGORY: "Upper",
}

FULL_BODY_CATEGORIES = {"Dresses", "Jumpsuits", "Sets", "Swimwear"}
ACCESSORY_CATEGORIES = {"Bags", "Accessories"}
TOP_COMPATIBLE_CATEGORIES = {"Activewear", "Intimates"}
NEUTRAL_COLORS = {"black", "white", "gray", "grey", "beige", "brown", "navy", "unknown"}

COLD_WEATHER_F = 45
COOL_WEATHER_F = 65
MODERATE_WEATHER_F = 72
LAYERING_MAX_WEATHER_F = 78

SPARSE_PRIMARY_LIMIT = 6
SPARSE_SECONDARY_LIMIT = 4
SPARSE_TERTIARY_LIMIT = 3
RECOMMENDATION_PRIMARY_SLOT_LIMIT = 8
RECOMMENDATION_OPTIONAL_SLOT_LIMIT = 6
RECOMMENDATION_PRIMARY_SHORTLIST_LIMIT = 4
RECOMMENDATION_OPTIONAL_SHORTLIST_LIMIT = 3
RECOMMENDATION_MAX_CANDIDATES = 400
MIN_RECOMMENDATION_SCORE = 18
MAX_SEMANTIC_SCORE = 30.0
STRONG_SEMANTIC_SCORE = 24
ACCEPTABLE_SEMANTIC_SCORE = 15
STRONG_OCCASION_SCORE = 21
FLEXIBLE_OCCASION_SCORE = 15
MAX_COLOR_SCORE = 25
MAX_STYLE_SCORE = 20
MAX_COMPLETENESS_SCORE = 20
