export type UserRole = "student" | "professor" | "admin";

export type CourseAgentStatus = "draft" | "active" | "disabled";

export type CourseMaterialStatus =
  | "uploaded"
  | "processing"
  | "ready"
  | "failed";

export type ChatSessionStatus = "open" | "archived";

export type ChatMessageRole = "user" | "assistant" | "system";

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  department?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Course {
  id: string;
  code: string;
  title: string;
  term: string;
  instructorId: string;
  instructorName: string;
  agentStatus: CourseAgentStatus;
  createdAt: string;
  updatedAt: string;
}

export interface CourseMaterial {
  id: string;
  courseId: string;
  uploadedBy: string;
  title: string;
  fileName: string;
  fileType: string;
  storageUri: string;
  status: CourseMaterialStatus;
  checksum?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface DocumentChunk {
  id: string;
  materialId: string;
  courseId: string;
  chunkIndex: number;
  content: string;
  embeddingModel?: string | null;
  tokenCount?: number | null;
  metadata: Record<string, unknown>;
  createdAt: string;
}

export interface Citation {
  materialId: string;
  chunkId: string;
  title: string;
  page?: number | null;
  score?: number | null;
  snippet?: string | null;
}

export interface ChatSession {
  id: string;
  userId: string;
  courseId: string;
  title?: string | null;
  status: ChatSessionStatus;
  createdAt: string;
  updatedAt: string;
}

export interface ChatLog {
  id: string;
  sessionId: string;
  courseId: string;
  userId: string;
  role: ChatMessageRole;
  message: string;
  citations: Citation[];
  latencyMs?: number | null;
  createdAt: string;
}
