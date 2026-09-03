import type { components } from "./lib/generated/api-types";

type ApiSchema<Name extends keyof components["schemas"]> = components["schemas"][Name];
type WithRequired<T, K extends keyof T> = T & Required<Pick<T, K>>;

export type ClothingItem = WithRequired<ApiSchema<"ClothingItemRecord">, "id" | "created_at">;
export type ClothingItemUpdateRequest = ApiSchema<"ClothingItemUpdateRequest">;
export type ClosetSummary = ApiSchema<"ClosetSummaryResponse">;
export type BatchUploadResponse = ApiSchema<"BatchUploadResponse">;
export type SignedUrlContract = ApiSchema<"SignedUrlContract">;
export type TaxonomyResponse = ApiSchema<"TaxonomyResponse">;
export type RecommendationBreakdown = ApiSchema<"RecommendationBreakdown">;
export type OutfitRecommendation = ApiSchema<"OutfitRecommendationRecord">;
export type RecommendationsRequest = ApiSchema<"RecommendationsRequest">;
export type RecommendationsResponse = ApiSchema<"RecommendationsResponse">;
export type TodayRecommendationResponse = ApiSchema<"TodayRecommendationResponse">;
export type UserPreferences = ApiSchema<"UserPreferencesResponse"> & {
  temperature_unit: "F" | "C";
  preferences: Record<string, unknown>;
};
export type UserPreferencesUpdateRequest = ApiSchema<"UserPreferencesUpdateRequest">;
export type SkillCallRecord = ApiSchema<"SkillCallRecord">;
export type ChatRequest = ApiSchema<"ChatRequest">;
export type ChatResponse = ApiSchema<"ChatResponse">;
