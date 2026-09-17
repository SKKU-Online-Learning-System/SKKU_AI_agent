import { ApiError, apiConnectionErrorMessage, apiRequest, readAccessToken } from "./api";

export type VoiceMode = "socratic";

export type VoicePlotPoint = { x: number; y: number };

export type VoiceVisualization = {
  title: string;
  kind: "formula" | "flow" | "plot" | "pdf";
  caption: string;
  latex: string;
  labels: string[];
  points: VoicePlotPoint[];
  x_label: string;
  y_label: string;
  file?: string;
  page?: number;
  material_id?: string;
};

export type VoiceMaterialSource = {
  material_id: string;
  document_name: string;
  page_number?: number | null;
  chunk_index: number;
  score: number;
};

/** How far the private index of a long PDF is; only such files carry one. */
export type VoiceAttachmentIndex = {
  status: "indexing" | "ready" | "failed";
  pages: number;
  pages_done: number;
  chunks?: number;
  message?: string | null;
};

/** A file the student attached to a typed question: an image or a PDF. */
export type VoiceAttachment = {
  id: string;
  name: string;
  kind: "image" | "pdf";
  size: number;
  pages: number;
  /** Characters read from the file; 0 until the turn that carries it has run. */
  chars: number;
  /**
   * "inline": the whole file goes into the turn as text. "excerpt": a long PDF,
   * indexed after upload; each question pulls only the pages that match it.
   * "vision": the image itself was handed to the text model.
   */
  mode?: "inline" | "excerpt" | "vision";
  /** Pages of an excerpted PDF that the last turn actually used. */
  pages_used?: number[];
  index?: VoiceAttachmentIndex | null;
};

/**
 * One line of the agent's work while it answers. The server addresses a step by
 * `key`: the first event with a key adds the line, later ones update it in place,
 * so "searching…" becomes "found 3" where it was.
 */
export type VoiceTraceStep = {
  key: string;
  stage: string;
  state: "running" | "done" | "failed";
  label: string;
  detail?: string;
  elapsed_ms?: number;
  /** The model's raw reasoning that streamed while this step ran (client-side accumulation). */
  thinking?: string;
  /** Paced one-line headlines of that reasoning, in Korean (client-side accumulation). */
  thoughts?: string[];
};

export type VoiceAnswer = {
  transcript: string;
  reply: string;
  tools: string[];
  sources: string[];
  visualizations: VoiceVisualization[];
  timings: Record<string, number>;
  material_sources: VoiceMaterialSource[];
  safety: {
    blocked: boolean;
    category: string;
    reason?: string | null;
    redirect_type?: string | null;
  };
  attachments: VoiceAttachment[];
  session_id: string;
  log_id: string;
};

export type VoiceQuestionPayload = {
  text: string;
  mode: VoiceMode;
  chat_session_id?: string | null;
  attachment_ids?: string[];
};

/** Callbacks for the events a streamed turn emits before and around the answer. */
export type VoiceStreamHandlers = {
  /** A delta of the answer text. */
  onToken: (token: string) => void;
  /** The progress notice composed from the question. */
  onStatus?: (message: string) => void;
  /** A trace step added or updated. */
  onStep?: (step: VoiceTraceStep) => void;
  /**
   * A delta of the model's own reasoning; shown, never part of the answer.
   * `stepKey` names the step (a model round) the thought belongs to.
   */
  onThinking?: (text: string, stepKey?: string) => void;
  /** One headline of what the model is doing now, keyed to its step. */
  onThought?: (text: string, stepKey?: string) => void;
  /** The answer text streamed so far was a discarded draft; the next tokens replace it. */
  onRewind?: () => void;
};

export type VoiceServiceStatus = {
  enabled: boolean;
  provider: string;
  services: Record<string, { available?: boolean; detail?: string }>;
  detail: string;
};

export type VoiceConfig = {
  course_id: string;
  course_name: string;
  term: string;
  voice_enabled: boolean;
  /** Which realtime transport the backend selected; the UI stays provider-neutral. */
  voice_provider: string;
  voice_status: VoiceServiceStatus;
  material_count: number;
  is_search_ready: boolean;
  can_manage: boolean;
  trusted_sites: string[];
};

export type WeakConcept = {
  memory_id: string;
  concept: string;
  difficulty_note: string;
  status: "new" | "practicing" | "mastered";
  mastery_percent: number;
  success_count: number;
  failure_count: number;
  last_seen_at: number;
  next_review_at: number;
};

function apiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export function getVoiceConfig(courseId: string): Promise<VoiceConfig> {
  return apiRequest<VoiceConfig>(`/api/voice/courses/${courseId}/config`);
}

export function resetVoiceConversation(courseId: string): Promise<{ ok: boolean }> {
  return apiRequest<{ ok: boolean }>(`/api/voice/courses/${courseId}/reset`, { method: "POST" });
}

export function listWeakConcepts(courseId: string): Promise<{ concepts: WeakConcept[] }> {
  return apiRequest<{ concepts: WeakConcept[] }>(
    `/api/voice/courses/${courseId}/weak-concepts`
  );
}

export function listVoiceTrustedSites(courseId: string): Promise<{ sites: string[] }> {
  return apiRequest<{ sites: string[] }>(`/api/voice/courses/${courseId}/trusted-sites`);
}

export function addVoiceTrustedSite(
  courseId: string,
  url: string
): Promise<{ sites: string[] }> {
  return apiRequest<{ sites: string[] }>(`/api/voice/courses/${courseId}/trusted-sites`, {
    body: JSON.stringify({ url }),
    method: "POST"
  });
}

export function removeVoiceTrustedSite(
  courseId: string,
  url: string
): Promise<{ sites: string[] }> {
  return apiRequest<{ sites: string[] }>(`/api/voice/courses/${courseId}/trusted-sites`, {
    body: JSON.stringify({ url }),
    method: "DELETE"
  });
}

/** WebSocket URL for the hands-free voice session; the JWT rides the query string. */
export function voiceStreamUrl(courseId: string, sessionId?: string | null): string {
  const base = apiBaseUrl().replace(/^http/, "ws");
  const token = readAccessToken() ?? "";
  const params = new URLSearchParams({ token });
  if (sessionId) params.set("chat_session_id", sessionId);
  return `${base}/api/voice/courses/${courseId}/stream?${params}`;
}

/** Upload one image or PDF for the learner's next typed question. */
export function uploadVoiceAttachment(courseId: string, file: File): Promise<VoiceAttachment> {
  const body = new FormData();
  body.set("file", file);
  return apiRequest<VoiceAttachment>(`/api/voice/courses/${courseId}/attachments`, {
    body,
    method: "POST"
  });
}

/** How an uploaded file stands; polled while a long PDF is being indexed. */
export function getVoiceAttachment(courseId: string, attachmentId: string): Promise<VoiceAttachment> {
  return apiRequest<VoiceAttachment>(`/api/voice/courses/${courseId}/attachments/${attachmentId}`);
}

/** Forget an attachment the learner removed before sending. */
export function deleteVoiceAttachment(courseId: string, attachmentId: string): Promise<void> {
  return apiRequest<void>(`/api/voice/courses/${courseId}/attachments/${attachmentId}`, {
    method: "DELETE"
  });
}

export async function fetchVoicePdfUrl(courseId: string, materialId: string): Promise<string> {
  const token = readAccessToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(
    `${apiBaseUrl()}/api/courses/${courseId}/materials/${materialId}/content`,
    { headers }
  );
  if (!response.ok) {
    throw new ApiError(response.status, "PDF 페이지를 불러오지 못했습니다.");
  }
  return URL.createObjectURL(await response.blob());
}

/**
 * Stream one typed question. Trace steps, the model's reasoning and answer
 * tokens arrive through the handlers as they are generated; the resolved value
 * is the final `done` event.
 */
export async function streamVoiceAnswer(
  courseId: string,
  payload: VoiceQuestionPayload,
  handlers: VoiceStreamHandlers
): Promise<VoiceAnswer> {
  const { onToken, onStatus, onStep, onThinking, onThought, onRewind } = handlers;
  const token = readAccessToken();
  const headers = new Headers({ "Content-Type": "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}/api/voice/courses/${courseId}/answer-text/stream`, {
      body: JSON.stringify(payload),
      headers,
      method: "POST"
    });
  } catch {
    throw new ApiError(0, apiConnectionErrorMessage);
  }

  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new ApiError(response.status, body.detail ?? "답변을 생성하지 못했습니다.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: VoiceAnswer | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line) continue;
      const event = JSON.parse(line) as { type: string } & Record<string, unknown>;
      if (event.type === "token") {
        onToken(String(event.text ?? ""));
      } else if (event.type === "status") {
        onStatus?.(String(event.text ?? ""));
      } else if (event.type === "step") {
        onStep?.(event as unknown as VoiceTraceStep);
      } else if (event.type === "thinking") {
        onThinking?.(
          String(event.text ?? ""),
          typeof event.key === "string" ? event.key : undefined
        );
      } else if (event.type === "thought") {
        onThought?.(
          String(event.text ?? ""),
          typeof event.key === "string" ? event.key : undefined
        );
      } else if (event.type === "rewind") {
        onRewind?.();
      } else if (event.type === "done") {
        result = event as unknown as VoiceAnswer;
      } else if (event.type === "error") {
        throw new ApiError(503, String(event.message ?? "답변 생성에 실패했습니다."));
      }
    }
    if (done) break;
  }

  if (!result) throw new ApiError(503, "응답 스트림이 예기치 않게 종료되었습니다.");
  return result;
}
