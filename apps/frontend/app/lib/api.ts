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

export type CourseSummary = {
  id: string;
  code: string;
  title: string;
  term: string;
  instructorId: string;
  instructorName: string;
  agentStatus: "draft" | "active" | "disabled";
  createdAt: string;
  updatedAt: string;
};

export type CourseMaterial = {
  id: string;
  courseId: string;
  uploadedBy: string;
  originalFileName: string;
  fileType: string;
  fileSize: number;
  week: number;
  processingStatus: "pending" | "processing" | "completed" | "failed";
  processingError?: string | null;
  chunkCount?: number;
  createdAt: string;
  updatedAt: string;
};

export type CourseRagStatus = {
  courseId: string;
  materialCount: number;
  completedMaterialCount: number;
  failedMaterialCount: number;
  chunkCount: number;
  embeddedChunkCount: number;
  isSearchReady: boolean;
};

export type MaterialProcessingStatus = {
  materialId: string;
  processingStatus: CourseMaterial["processingStatus"];
  processingError?: string | null;
  chunkCount: number;
  updatedAt: string;
};

export type RagSearchResult = {
  chunkId: string;
  materialId: string;
  documentName: string;
  pageNumber?: number | null;
  chunkIndex: number;
  chunkText: string;
  score: number;
};

export type RagSearchResponse = {
  courseId: string;
  question: string;
  topK: number;
  results: RagSearchResult[];
  debug?: {
    embeddingModel?: string | null;
    searchMode: string;
    scoreThreshold?: number | null;
    totalCandidateChunks: number;
  };
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

export function listCourses(): Promise<CourseSummary[]> {
  return apiRequest<CourseSummary[]>("/api/courses");
}

export function listCourseMaterials(courseId: string): Promise<CourseMaterial[]> {
  return apiRequest<CourseMaterial[]>(`/api/courses/${courseId}/materials`);
}

export function uploadCourseMaterial(
  courseId: string,
  file: File,
  week: number
): Promise<CourseMaterial> {
  const body = new FormData();
  body.set("file", file);
  body.set("week", String(week));
  return apiRequest<CourseMaterial>(`/api/courses/${courseId}/materials`, {
    body,
    method: "POST"
  });
}

export async function downloadCourseMaterial(
  courseId: string,
  materialId: string
): Promise<Blob> {
  const token = readAccessToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(
      `${getApiBaseUrl()}/api/courses/${courseId}/materials/${materialId}/download`,
      { headers }
    );
  } catch {
    throw new ApiError(0, apiConnectionErrorMessage);
  }
  if (!response.ok) throw new ApiError(response.status, await readErrorMessage(response));
  return response.blob();
}

export function deleteCourseMaterial(courseId: string, materialId: string): Promise<void> {
  return apiRequest<void>(`/api/courses/${courseId}/materials/${materialId}`, {
    method: "DELETE"
  });
}

export function processCourseMaterial(
  courseId: string,
  materialId: string,
  reprocess = false
): Promise<MaterialProcessingStatus> {
  return apiRequest<MaterialProcessingStatus>(
    `/api/courses/${courseId}/materials/${materialId}/${reprocess ? "reprocess" : "process"}`,
    { method: "POST" }
  );
}

export async function getCourseRagStatus(courseId: string): Promise<CourseRagStatus> {
  const status = await apiRequest<{
    course_id: string;
    material_count: number;
    completed_material_count: number;
    failed_material_count: number;
    chunk_count: number;
    embedded_chunk_count: number;
    is_search_ready: boolean;
  }>(`/api/courses/${courseId}/rag/status`);
  return {
    courseId: status.course_id,
    materialCount: status.material_count,
    completedMaterialCount: status.completed_material_count,
    failedMaterialCount: status.failed_material_count,
    chunkCount: status.chunk_count,
    embeddedChunkCount: status.embedded_chunk_count,
    isSearchReady: status.is_search_ready
  };
}

export async function searchRagDebug(
  courseId: string,
  question: string,
  topK: number
): Promise<RagSearchResponse> {
  const response = await apiRequest<{
    course_id: string;
    question: string;
    top_k: number;
    results: Array<{
      chunk_id: string;
      material_id: string;
      document_name: string;
      page_number?: number | null;
      chunk_index: number;
      chunk_text: string;
      score: number;
    }>;
    debug?: {
      embedding_model?: string | null;
      search_mode: string;
      score_threshold?: number | null;
      total_candidate_chunks: number;
    } | null;
  }>("/api/rag/search", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId, question, top_k: topK, debug: true })
  });

  return {
    courseId: response.course_id,
    question: response.question,
    topK: response.top_k,
    results: response.results.map((result) => ({
      chunkId: result.chunk_id,
      materialId: result.material_id,
      documentName: result.document_name,
      pageNumber: result.page_number,
      chunkIndex: result.chunk_index,
      chunkText: result.chunk_text,
      score: result.score
    })),
    debug: response.debug
      ? {
          embeddingModel: response.debug.embedding_model,
          searchMode: response.debug.search_mode,
          scoreThreshold: response.debug.score_threshold,
          totalCandidateChunks: response.debug.total_candidate_chunks
        }
      : undefined
  };
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
