import { ApiError, apiConnectionErrorMessage, apiRequest, readAccessToken } from "./api";

export type VoiceMode = "explain" | "socratic";

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
  session_id: string;
  log_id: string;
};

export type VoiceConfig = {
  course_id: string;
  course_name: string;
  term: string;
  voice_enabled: boolean;
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
export function voiceStreamUrl(courseId: string, mode: VoiceMode): string {
  const base = apiBaseUrl().replace(/^http/, "ws");
  const token = readAccessToken() ?? "";
  return `${base}/api/voice/courses/${courseId}/stream?mode=${mode}&token=${encodeURIComponent(token)}`;
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
 * Stream one typed question. Answer tokens arrive through `onToken` as they are
 * generated; the resolved value is the final `done` event.
 */
export async function streamVoiceAnswer(
  courseId: string,
  payload: { text: string; mode: VoiceMode; chat_session_id?: string | null },
  onToken: (token: string) => void,
  onStatus?: (message: string) => void
): Promise<VoiceAnswer> {
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
