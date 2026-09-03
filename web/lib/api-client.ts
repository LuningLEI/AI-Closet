import { typedRequest, uploadFile } from "./api";
import type { ApiQuery } from "./api";
import type {
  BatchUploadResponse,
  ChatRequest,
  ChatResponse,
  ClothingItem,
  ClothingItemUpdateRequest,
  ClosetSummary,
  RecommendationsRequest,
  RecommendationsResponse,
  SignedUrlContract,
  TaxonomyResponse,
  TodayRecommendationResponse,
  UserPreferences,
  UserPreferencesUpdateRequest,
} from "../types";

export type TodayRecommendationQuery = ApiQuery<"/api/v1/today/recommendation", "get">;

export const apiClient = {
  storage: {
    signedUrlContract: async (): Promise<SignedUrlContract> =>
      typedRequest("/api/v1/storage/signed-url-contract", { method: "get" }),
  },
  taxonomy: {
    get: async (): Promise<TaxonomyResponse> => typedRequest("/api/v1/taxonomy", { method: "get" }),
  },
  items: {
    list: async (): Promise<ClothingItem[]> =>
      typedRequest("/api/v1/items", { method: "get" }) as Promise<ClothingItem[]>,
    summary: async (): Promise<ClosetSummary> => typedRequest("/api/v1/summary", { method: "get" }),
    update: async (itemId: string, body: ClothingItemUpdateRequest): Promise<ClothingItem> =>
      typedRequest("/api/v1/items/{item_id}", {
        method: "patch",
        pathParams: { item_id: itemId },
        body,
      }) as Promise<ClothingItem>,
    uploadBatch: (formData: FormData) => uploadFile<BatchUploadResponse>("/api/v1/items/upload-batch", formData),
  },
  preferences: {
    get: async (): Promise<UserPreferences> =>
      typedRequest("/api/v1/preferences", { method: "get" }) as Promise<UserPreferences>,
    update: async (body: UserPreferencesUpdateRequest): Promise<UserPreferences> =>
      typedRequest("/api/v1/preferences", {
        method: "patch",
        body,
      }) as Promise<UserPreferences>,
  },
  profile: {
    uploadAvatar: (formData: FormData) => uploadFile<UserPreferences>("/api/v1/profile/avatar", formData),
  },
  recommendations: {
    create: async (body: RecommendationsRequest): Promise<RecommendationsResponse> =>
      typedRequest("/api/v1/recommendations", {
        method: "post",
        body,
      }),
    today: async (query?: TodayRecommendationQuery): Promise<TodayRecommendationResponse> =>
      typedRequest("/api/v1/today/recommendation", {
        method: "get",
        query,
      }),
  },
  chat: {
    send: async (body: ChatRequest): Promise<ChatResponse> =>
      typedRequest("/api/v1/chat", {
        method: "post",
        body,
      }),
  },
};
