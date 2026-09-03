import { supabase } from "./supabase";
import { DEFAULT_USER_ID, USER_STORAGE_KEY } from "./constants";
import type { paths } from "./generated/api-types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

export function apiUrl(path: string) {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export type ApiPath = keyof paths;
export type ApiMethod<Path extends ApiPath> = keyof paths[Path] & Lowercase<string>;
export type ApiOperation<Path extends ApiPath, Method extends ApiMethod<Path>> = NonNullable<paths[Path][Method]>;
export type ApiQuery<Path extends ApiPath, Method extends ApiMethod<Path>> =
  ApiOperation<Path, Method> extends { parameters: { query?: infer Query } } ? Query : never;
export type ApiJsonBody<Path extends ApiPath, Method extends ApiMethod<Path>> =
  ApiOperation<Path, Method> extends { requestBody: { content: { "application/json": infer Body } } } ? Body : never;
export type ApiResponse<Path extends ApiPath, Method extends ApiMethod<Path>> =
  ApiOperation<Path, Method> extends { responses: { 200: { content: { "application/json": infer Response } } } }
    ? Response
    : never;

type TypedRequestOptions<Path extends ApiPath, Method extends ApiMethod<Path>> = {
  method: Method;
  pathParams?: Record<string, string>;
  query?: ApiQuery<Path, Method>;
  body?: ApiJsonBody<Path, Method>;
  formData?: FormData;
};

export function currentUserId() {
  if (typeof window === "undefined") {
    return DEFAULT_USER_ID;
  }
  return window.localStorage.getItem(USER_STORAGE_KEY) || DEFAULT_USER_ID;
}

async function authHeaders(): Promise<Record<string, string>> {
  if (!supabase) {
    return { "X-AI-Closet-User-Id": currentUserId() };
  }

  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;
  if (accessToken) {
    return { Authorization: `Bearer ${accessToken}` };
  }
  return {};
}

export async function fetcher<T>(input: string, init?: RequestInit): Promise<T> {
  const nextAuthHeaders = await authHeaders();
  const response = await fetch(apiUrl(input), {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...nextAuthHeaders,
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "API request failed");
  }

  return response.json() as Promise<T>;
}

export async function typedRequest<Path extends ApiPath, Method extends ApiMethod<Path>>(
  path: Path,
  options: TypedRequestOptions<Path, Method>,
): Promise<ApiResponse<Path, Method>> {
  const requestPath = withQuery(replacePathParams(path, options.pathParams), options.query);
  return fetcher<ApiResponse<Path, Method>>(requestPath, {
    method: options.method.toUpperCase(),
    body: options.formData ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
  });
}

export async function uploadFile<T>(path: string, formData: FormData): Promise<T> {
  const nextAuthHeaders = await authHeaders();
  const response = await fetch(apiUrl(path), {
    cache: "no-store",
    method: "POST",
    headers: nextAuthHeaders,
    body: formData,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Upload failed");
  }

  return response.json() as Promise<T>;
}

export async function sendJson<T>(path: string, method: string, body: unknown): Promise<T> {
  return fetcher<T>(path, {
    method,
    body: JSON.stringify(body),
  });
}

function replacePathParams(path: string, params?: Record<string, string>) {
  if (!params) {
    return path;
  }
  return Object.entries(params).reduce(
    (nextPath, [key, value]) => nextPath.replace(`{${key}}`, encodeURIComponent(value)),
    path,
  );
}

function withQuery<Query>(path: string, query?: Query) {
  if (!query || typeof query !== "object") {
    return path;
  }
  const searchParams = new URLSearchParams();
  Object.entries(query as Record<string, unknown>).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  });
  const queryString = searchParams.toString();
  return queryString ? `${path}?${queryString}` : path;
}
