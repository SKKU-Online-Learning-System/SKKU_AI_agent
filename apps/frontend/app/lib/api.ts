import type { AuthUser } from "./auth";
import type { UserRole } from "@skku-course-agent/shared";

export const accessTokenStorageKey = "skku-course-agent-access-token-v1";
export const apiConnectionErrorMessage =
  "API 서버에 연결할 수 없습니다. 백엔드 실행 상태와 API 주소를 확인해 주세요.";

type ApiRequestOptions = RequestInit & {
  accessToken?: string | null;
  skipAuth?: boolean;
};

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};

export type AdminUser = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  department?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AdminCourse = {
  id: string;
  name: string;
  semester: string;
  description?: string | null;
  professorId: string;
  professorName: string;
  isActive: boolean;
  studentAccessCount: number;
  createdAt: string;
  updatedAt: string;
};

export type AdminCoursePayload = {
  name: string;
  semester: string;
  description?: string | null;
  professorId: string;
  isActive: boolean;
};

export type AdminCourseFilters = {
  semester?: string;
  isActive?: boolean | null;
  professorId?: string;
  keyword?: string;
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

  let response: Response;
  try {
    response = await fetch(`${getApiBaseUrl()}${path}`, {
      ...fetchOptions,
      headers
    });
  } catch {
    throw new ApiError(0, apiConnectionErrorMessage);
  }

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

function adminCourseQuery(filters: AdminCourseFilters = {}): string {
  const params = new URLSearchParams();
  if (filters.semester) params.set("semester", filters.semester);
  if (filters.isActive !== undefined && filters.isActive !== null) {
    params.set("is_active", String(filters.isActive));
  }
  if (filters.professorId) params.set("professor_id", filters.professorId);
  if (filters.keyword) params.set("keyword", filters.keyword);

  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listAdminCourses(
  filters: AdminCourseFilters = {}
): Promise<AdminCourse[]> {
  return apiRequest<AdminCourse[]>(`/api/admin/courses${adminCourseQuery(filters)}`);
}

export function getAdminCourse(courseId: string): Promise<AdminCourse> {
  return apiRequest<AdminCourse>(`/api/admin/courses/${courseId}`);
}

export function createAdminCourse(payload: AdminCoursePayload): Promise<AdminCourse> {
  return apiRequest<AdminCourse>("/api/admin/courses", {
    body: JSON.stringify(payload),
    method: "POST"
  });
}

export function updateAdminCourse(
  courseId: string,
  payload: AdminCoursePayload
): Promise<AdminCourse> {
  return apiRequest<AdminCourse>(`/api/admin/courses/${courseId}`, {
    body: JSON.stringify(payload),
    method: "PATCH"
  });
}

export function activateAdminCourse(courseId: string): Promise<AdminCourse> {
  return apiRequest<AdminCourse>(`/api/admin/courses/${courseId}/activate`, {
    method: "PATCH"
  });
}

export function deactivateAdminCourse(courseId: string): Promise<AdminCourse> {
  return apiRequest<AdminCourse>(`/api/admin/courses/${courseId}/deactivate`, {
    method: "PATCH"
  });
}

export function listAdminUsers(role?: UserRole): Promise<AdminUser[]> {
  const query = role ? `?role=${role}` : "";
  return apiRequest<AdminUser[]>(`/api/admin/users${query}`);
}
