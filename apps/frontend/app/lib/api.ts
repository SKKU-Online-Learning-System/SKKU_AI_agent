import type { AuthUser } from "./auth";

export const accessTokenStorageKey = "skku-course-agent-access-token-v1";

type ApiRequestOptions = RequestInit & {
  accessToken?: string | null;
  skipAuth?: boolean;
};

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
    /\/$/,
    ""
  );
}

export function readAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(accessTokenStorageKey);
}

export function saveAccessToken(accessToken: string): void {
  window.localStorage.setItem(accessTokenStorageKey, accessToken);
}

export function clearAccessToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(accessTokenStorageKey);
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    return response.statusText || "API request failed";
  }

  return response.statusText || "API request failed";
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {}
): Promise<T> {
  const { accessToken, skipAuth, ...fetchOptions } = options;
  const headers = new Headers(fetchOptions.headers);
  const token = skipAuth ? null : accessToken ?? readAccessToken();

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (fetchOptions.body && !(fetchOptions.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...fetchOptions,
    headers
  });

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function loginRequest(email: string, password: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/api/auth/login", {
    body: JSON.stringify({ email, password }),
    method: "POST",
    skipAuth: true
  });
}

export function fetchCurrentUser(accessToken?: string | null): Promise<AuthUser> {
  return apiRequest<AuthUser>("/api/auth/me", { accessToken });
}
