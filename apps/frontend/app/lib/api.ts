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

export type MaterialProcessingStatus = {
  materialId: string;
  processingStatus: CourseMaterial["processingStatus"];
  processingError?: string | null;
  chunkCount: number;
  embeddingModel?: string | null;
  updatedAt: string;
};

export type CourseRagStatus = {
  courseId: string;
  materialCount: number;
  completedMaterialCount: number;
  failedMaterialCount: number;
  pendingMaterialCount: number;
  chunkCount: number;
  embeddedChunkCount: number;
  isSearchReady: boolean;
};

export type AnswerSourceType =
  | "rag"
  | "general_llm"
  | "safety_response"
  | "no_material";

export type SafetyCategory =
  | "normal"
  | "assignment_direct_answer"
  | "exam_direct_answer"
  | "privacy_request"
  | "prompt_injection"
  | "unsafe_content";

export type AnswerSource = {
  materialId: string;
  documentName: string;
  pageNumber?: number | null;
  chunkIndex: number;
  score: number;
};

export type RagSearchResult = {
  chunkId: string;
  materialId: string;
  documentName: string;
  pageNumber?: number | null;
  chunkIndex: number;
  chunkText: string;
  score: number;
  pageImageUrl?: string | null;
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
    textScoreThreshold?: number | null;
    totalCandidateChunks: number;
  };
};

export type ChatAnswer = {
  sessionId: string;
  logId: string;
  answer: string;
  sources: AnswerSource[];
  isGrounded: boolean;
  answerSourceType: AnswerSourceType;
  modelName?: string | null;
  responseTimeMs?: number | null;
  retrievalSummary: {
    resultCount: number;
    maxScore?: number | null;
    scoreThreshold: number;
    reason?: string | null;
  };
  safety: {
    blocked: boolean;
    category: SafetyCategory;
    reason?: string | null;
    redirectType?: string | null;
  };
};

export type ChatAskPayload = {
  courseId: string;
  question: string;
  chatSessionId?: string | null;
  topK?: number;
};

export type ChatSessionSummary = {
  id: string;
  courseId: string;
  courseName: string;
  title?: string | null;
  messageCount: number;
  lastMessageAt?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type ChatHistoryAttachment = {
  id: string;
  name: string;
  kind: string;
  pages: number;
  size: number;
};

export type ChatHistoryLog = {
  id: string;
  question: string;
  answer: string;
  sources: AnswerSource[];
  /** Files the student attached to this question, without their extracted text. */
  attachments?: ChatHistoryAttachment[];
  isGrounded: boolean;
  answerSourceType: AnswerSourceType;
  createdAt: string;
};

export type ChatSessionDetail = {
  session: ChatSessionSummary;
  logs: ChatHistoryLog[];
};

export type ChatLogListItem = {
  id: string;
  courseId: string;
  courseName: string;
  userLabel: string;
  userId?: string | null;
  question: string;
  answerPreview: string;
  isGrounded: boolean;
  answerSourceType: AnswerSourceType;
  safetyCategory: SafetyCategory;
  createdAt: string;
};

export type ChatLogDetail = {
  id: string;
  courseId: string;
  courseName: string;
  userLabel: string;
  userId?: string | null;
  question: string;
  answer: string;
  referencedDocuments: AnswerSource[];
  retrievalResult: Record<string, unknown>;
  safetyResult: Record<string, unknown>;
  isGrounded: boolean;
  answerSourceType: AnswerSourceType;
  modelName?: string | null;
  responseTimeMs?: number | null;
  createdAt: string;
};

export type ChatLogListResponse = {
  logs: ChatLogListItem[];
  total: number;
};

export type ChatLogFilters = {
  courseId?: string;
  userId?: string;
  keyword?: string;
  isGrounded?: boolean | null;
  safetyCategory?: string;
  from?: string;
  to?: string;
  limit?: number;
};

export type CourseStatistic = {
  courseId: string;
  courseName: string;
  questionCount: number;
  userCount: number;
  materialCount: number;
};

export type DateStatistic = { date: string; count: number };
export type RecentQuestion = {
  id: string;
  courseId: string;
  courseName: string;
  question: string;
  createdAt: string;
};
export type KeywordStatistic = { keyword: string; count: number };

export type ServiceStatistics = {
  totals: { courseCount: number; userCount: number; questionCount: number };
  questionsByDate: DateStatistic[];
  courses: CourseStatistic[];
};

export type ProfessorStatistics = {
  courses: CourseStatistic[];
  questionsByDate: DateStatistic[];
  recentQuestions: RecentQuestion[];
  keywords: KeywordStatistic[];
};

export type MyStatistics = {
  questionCount: number;
  sessionCount: number;
  questionsByDate: DateStatistic[];
  courses: Array<Pick<CourseStatistic, "courseId" | "courseName" | "questionCount">>;
};

/** Weak concepts the course agent captured, aggregated for the teaching side. */
export type WeakConceptStatus = "new" | "practicing" | "mastered";
export type WeakConceptStatusCounts = Record<WeakConceptStatus, number>;

export type WeakConceptCourseSummary = {
  courseId: string;
  courseName: string;
  recordCount: number;
  conceptCount: number;
  studentCount: number;
  statusCounts: WeakConceptStatusCounts;
  averageMastery: number;
  dueReviewCount: number;
  lastActivityAt: string | null;
};

export type WeakConceptStatistics = {
  totals: Omit<WeakConceptCourseSummary, "courseId" | "courseName"> & { courseCount: number };
  courses: WeakConceptCourseSummary[];
};

export type WeakConceptConceptRow = {
  concept: string;
  topic: string;
  detail: string;
  studentCount: number;
  failureCount: number;
  successCount: number;
  statusCounts: WeakConceptStatusCounts;
  averageMastery: number;
  lastSeenAt: string | null;
  sampleNotes: string[];
};

export type WeakConceptTopicRow = {
  topic: string;
  conceptCount: number;
  studentCount: number;
  failureCount: number;
  averageMastery: number;
};

export type WeakConceptStudentRow = {
  studentId: string;
  label: string;
  conceptCount: number;
  statusCounts: WeakConceptStatusCounts;
  averageMastery: number;
  dueReviewCount: number;
  lastSeenAt: string | null;
  weakestConcepts: string[];
};

export type WeakConceptCapture = {
  concept: string;
  status: WeakConceptStatus;
  difficultyNote: string;
  studentLabel: string;
  masteryPercent: number;
  lastSeenAt: string | null;
};

export type CourseWeakConceptStatistics = WeakConceptCourseSummary & {
  concepts: WeakConceptConceptRow[];
  topics: WeakConceptTopicRow[];
  students: WeakConceptStudentRow[];
  savedByDate: DateStatistic[];
  recentCaptures: WeakConceptCapture[];
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

export function downloadCourseMaterial(courseId: string, materialId: string): Promise<Blob> {
  return fetchAuthorizedBlob(`/api/courses/${courseId}/materials/${materialId}/download`);
}

export function fetchMaterialPageImage(
  courseId: string, materialId: string, page: number
): Promise<Blob> {
  return fetchAuthorizedBlob(`/api/courses/${courseId}/materials/${materialId}/pages/${page}/image`);
}

async function fetchAuthorizedBlob(path: string): Promise<Blob> {
  const token = readAccessToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(
      `${getApiBaseUrl()}${path}`,
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
  materialId: string
): Promise<MaterialProcessingStatus> {
  return apiRequest<MaterialProcessingStatus>(
    `/api/courses/${courseId}/materials/${materialId}/process`,
    { method: "POST" }
  );
}

export function reprocessCourseMaterial(
  courseId: string,
  materialId: string
): Promise<MaterialProcessingStatus> {
  return apiRequest<MaterialProcessingStatus>(
    `/api/courses/${courseId}/materials/${materialId}/reprocess`,
    { method: "POST" }
  );
}

export function getMaterialProcessingStatus(
  courseId: string,
  materialId: string
): Promise<MaterialProcessingStatus> {
  return apiRequest<MaterialProcessingStatus>(
    `/api/courses/${courseId}/materials/${materialId}/processing-status`
  );
}

export function getCourseRagStatus(courseId: string): Promise<CourseRagStatus> {
  return apiRequest<CourseRagStatus>(`/api/courses/${courseId}/rag/status`);
}

export function searchRagDebug(
  courseId: string,
  question: string,
  topK: number
): Promise<RagSearchResponse> {
  return apiRequest<RagSearchResponse>("/api/rag/search", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId, question, top_k: topK, debug: true })
  });
}

export function askCourseAgent(payload: ChatAskPayload): Promise<ChatAnswer> {
  return apiRequest<ChatAnswer>("/api/chat", {
    body: JSON.stringify(payload),
    method: "POST"
  });
}

export function listChatSessions(courseId?: string): Promise<ChatSessionSummary[]> {
  const query = courseId ? `?course_id=${encodeURIComponent(courseId)}` : "";
  return apiRequest<ChatSessionSummary[]>(`/api/chat/sessions${query}`);
}

export function getChatSession(sessionId: string): Promise<ChatSessionDetail> {
  return apiRequest<ChatSessionDetail>(`/api/chat/sessions/${sessionId}`);
}

function chatLogQuery(filters: ChatLogFilters = {}): string {
  const params = new URLSearchParams();
  if (filters.courseId) params.set("course_id", filters.courseId);
  if (filters.userId) params.set("user_id", filters.userId);
  if (filters.keyword) params.set("keyword", filters.keyword);
  if (filters.isGrounded !== undefined && filters.isGrounded !== null) {
    params.set("is_grounded", String(filters.isGrounded));
  }
  if (filters.safetyCategory) params.set("safety_category", filters.safetyCategory);
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.limit) params.set("limit", String(filters.limit));

  const query = params.toString();
  return query ? `?${query}` : "";
}

export function listCourseChatLogs(
  courseId: string,
  filters: ChatLogFilters = {}
): Promise<ChatLogListResponse> {
  const { courseId: _ignored, ...rest } = filters;
  return apiRequest<ChatLogListResponse>(
    `/api/professor/courses/${courseId}/chat-logs${chatLogQuery(rest)}`
  );
}

export function listAdminChatLogs(
  filters: ChatLogFilters = {}
): Promise<ChatLogListResponse> {
  return apiRequest<ChatLogListResponse>(`/api/admin/chat-logs${chatLogQuery(filters)}`);
}

export function listOwnChatLogs(
  filters: ChatLogFilters = {}
): Promise<ChatLogListResponse> {
  return apiRequest<ChatLogListResponse>(`/api/student/chat-logs${chatLogQuery(filters)}`);
}

export function getServiceStatistics(): Promise<ServiceStatistics> {
  return apiRequest<ServiceStatistics>("/api/stats/service");
}

export function getProfessorStatistics(): Promise<ProfessorStatistics> {
  return apiRequest<ProfessorStatistics>("/api/stats/professor");
}

export function getMyStatistics(): Promise<MyStatistics> {
  return apiRequest<MyStatistics>("/api/stats/me");
}

export function getWeakConceptStatistics(): Promise<WeakConceptStatistics> {
  return apiRequest<WeakConceptStatistics>("/api/stats/weak-concepts");
}

export function getCourseWeakConceptStatistics(
  courseId: string
): Promise<CourseWeakConceptStatistics> {
  return apiRequest<CourseWeakConceptStatistics>(
    `/api/stats/weak-concepts/courses/${encodeURIComponent(courseId)}`
  );
}

export function getCourseChatLog(logId: string): Promise<ChatLogDetail> {
  return apiRequest<ChatLogDetail>(`/api/professor/chat-logs/${logId}`);
}

export function getAdminChatLog(logId: string): Promise<ChatLogDetail> {
  return apiRequest<ChatLogDetail>(`/api/admin/chat-logs/${logId}`);
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
