export const API_V1_PREFIX = "/api/v1";

export const DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000001";
export const USER_STORAGE_KEY = "ai-closet-user-id";

export const FILTER_ALL_VALUE = "All";
export const FILTER_ANY_VALUE = "Any";
export const CLOSET_RECOGNITION_POLL_INTERVAL_MS = 2500;

export const DEFAULT_CATEGORY = "Uncategorized";
export const DEFAULT_STYLE = "Casual";
export const DEFAULT_OCCASION = "Everyday";
export const DEFAULT_TEMPERATURE_F = 68;
export const DEFAULT_RECOMMENDATION_LIMIT = 3;
export const GEOLOCATION_MAX_AGE_MS = 1000 * 60 * 5;
export const GEOLOCATION_TIMEOUT_MS = 6500;

export const RECOGNITION_SOURCE = {
  ANALYZING: "Analyzing",
  FAILED: "Recognition Failed",
  MANUAL: "Manual",
} as const;

export const WEATHER_SOURCE = {
  BROWSER_GEOLOCATION: "browser-geolocation",
  IP_GEOLOCATION: "ip-geolocation",
  MANUAL_LOCATION: "manual-location",
} as const;

export const CATEGORY_OPTIONS = [
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
];

export const STYLE_OPTIONS = [
  DEFAULT_STYLE,
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
];

export const COLOR_OPTIONS = [
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
  "Unknown",
];

export const RECOMMENDATION_COLOR_OPTIONS = COLOR_OPTIONS.filter((color) => color !== "Multicolor" && color !== "Unknown");

export const OCCASION_OPTIONS = [
  DEFAULT_OCCASION,
  "Work",
  "Party",
  "Date",
  "Travel",
  "Workout",
  "Wedding",
  "Vacation",
  "Lounge",
  "Evening",
];

export const GENDER_OPTIONS = ["Prefer not to say", "Woman", "Man", "Non-binary", "Self-described"];
export const DEFAULT_DAILY_OCCASIONS = [DEFAULT_OCCASION, "Work"];
export const DEFAULT_STYLE_PREFERENCES = [DEFAULT_STYLE];

export const PROFILE_ONBOARDING_PENDING_KEY = "ai-closet-onboarding-pending";
export const PROFILE_UPDATED_EVENT = "ai-closet-profile-updated";
