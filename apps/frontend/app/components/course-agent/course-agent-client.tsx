"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getChatSession } from "../../lib/api";
import type { AnswerSource, ChatHistoryAttachment } from "../../lib/api";
import type {
  VoiceAnswer,
  VoiceAttachment,
  VoiceConfig,
  VoiceMaterialSource,
  VoiceTraceStep,
  VoiceVisualization,
  WeakConcept
} from "../../lib/voice-api";
import {
  deleteVoiceAttachment,
  getVoiceAttachment,
  getVoiceConfig,
  listWeakConcepts,
  resetVoiceConversation,
  streamVoiceAnswer,
  uploadVoiceAttachment,
  voiceStreamUrl
} from "../../lib/voice-api";
import { decodePcm16, newResampleState, resample } from "../../lib/pcm";
import { UiIcon } from "../ui/ui-icon";
import { CourseAgentSymbol } from "../ui/course-agent-symbol";
import type { CourseAgentSymbolState } from "../ui/course-agent-symbol";
import {
  appendThinking,
  appendThought,
  CourseAgentTrace,
  EMPTY_TRACE,
  failTrace,
  finishTrace,
  startTrace,
  upsertStep
} from "./course-agent-trace";
import type { TurnTrace } from "./course-agent-trace";
import { CourseAgentVisualizationCard } from "./course-agent-visualization";
import { MathText } from "./math-text";

const SAMPLE_RATE = 16000;
// The speech server emits 24 kHz PCM. The playback AudioContext must run at
// the same rate: at any other rate the browser resamples every chunk on its
// own, with no filter history carried across chunks, so each boundary gets a
// transient — an audible tick roughly three times a second.
const PLAYBACK_SAMPLE_RATE = 24000;
// Backoff for a realtime connection that drops on its own. Two quiet retries
// cover a brief network blip or a backend restart; after that the student is
// told, because silently closing the panel looked like the feature breaking.
const RECONNECT_DELAYS_MS = [1000, 3000];
const FRAME_SAMPLES = 320;
const MAX_PENDING_AUDIO_FRAMES = 250;
// Files one typed question may carry. The server enforces its own limit too;
// this only keeps the composer from offering more than it will accept.
const MAX_ATTACHMENTS = 4;
const ATTACHMENT_EXTENSIONS = /\.(png|jpe?g|webp|gif|bmp|pdf)$/i;
const ATTACHMENT_HINT_TYPES = "이미지 또는 PDF만 첨부할 수 있어요.";
// How often the composer asks how far a long PDF's index is.
const INDEX_POLL_MS = 1500;

type VoiceState = "idle" | "connecting" | "listening" | "hearing" | "thinking" | "speaking";

const VOICE_STATE_LABELS: Record<VoiceState, string> = {
  idle: "음성 시작",
  connecting: "음성 연결 중",
  listening: "듣는 중",
  hearing: "말씀 듣는 중",
  thinking: "응답 준비 중",
  speaking: "응답 중"
};

/** The single status line shown while a call is running. */
const VOICE_STATE_CAPTIONS: Record<VoiceState, string> = {
  idle: "대기 중",
  connecting: "연결 중",
  listening: "듣는 중",
  hearing: "말씀하시는 중",
  thinking: "생각하는 중",
  speaking: "답변하는 중"
};

const WEAK_CONCEPT_STATUS_LABELS: Record<WeakConcept["status"], string> = {
  new: "신규",
  practicing: "학습 중",
  mastered: "학습 완료"
};

/** An attachment as it appears on a sent message; the preview is a local object URL. */
type SentAttachment = VoiceAttachment & { previewUrl?: string | null };

/**
 * A file in the composer, from the moment it is picked until the turn is sent --
 * or, for a long PDF that is read by excerpt, until the student removes it: such
 * a file stays pinned across turns so every question can look things up in it.
 */
type PendingAttachment = {
  localId: number;
  file: File;
  previewUrl: string | null;
  status: "uploading" | "indexing" | "ready" | "error";
  attachment?: VoiceAttachment;
  error?: string;
  pinned?: boolean;
};

export type ChatEntry =
  | {
      kind: "message";
      id: number;
      role: "user" | "assistant";
      text: string;
      tools?: string[];
      webSources?: string[];
      materialSources?: VoiceMaterialSource[];
      attachments?: SentAttachment[];
      /** The agent's visible work for this turn; typed turns only. */
      trace?: TurnTrace;
      timing?: string;
      symbolState: CourseAgentSymbolState;
    }
  | { kind: "visualization"; id: number; visualization: VoiceVisualization };

const GREETING =
  "안녕하세요. COURSE AGENT입니다. 강의 내용 중 막힌 부분을 텍스트나 음성으로 질문해 주세요.";

/**
 * The part of the transcript the view follows as it changes: which entries are
 * shown and how much of each message has been written. The agent's trace is
 * left out on purpose -- it grows on every reasoning delta, and following it
 * pulled the student away from whatever they were reading.
 */
export function transcriptFollowKey(entries: readonly ChatEntry[]): string {
  return entries
    .map((entry) =>
      entry.kind === "message" ? `${entry.id}:${entry.text.length}` : `${entry.id}:visual`
    )
    .join(",");
}

function toBase64(bytes: Uint8Array): string {
  let value = "";
  bytes.forEach((byte) => {
    value += String.fromCharCode(byte);
  });
  return btoa(value);
}

function fromBase64(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

function sourceLabel(source: VoiceMaterialSource): string {
  return source.page_number
    ? `${source.document_name} p.${source.page_number}`
    : source.document_name;
}

/** Stored logs use the camelCase API shape; the live agent uses the wire shape. */
function toMaterialSource(source: AnswerSource): VoiceMaterialSource {
  return {
    material_id: source.materialId,
    document_name: source.documentName,
    page_number: source.pageNumber,
    chunk_index: source.chunkIndex,
    score: source.score
  };
}

function isAttachable(file: File): boolean {
  return (
    ATTACHMENT_EXTENSIONS.test(file.name) ||
    file.type.startsWith("image/") ||
    file.type === "application/pdf"
  );
}

/** Object URL for an image preview; jsdom and older browsers may not have it. */
function previewUrlFor(file: File): string | null {
  if (!file.type.startsWith("image/") || typeof URL.createObjectURL !== "function") return null;
  try {
    return URL.createObjectURL(file);
  } catch {
    return null;
  }
}

function revokePreview(url: string | null | undefined): void {
  if (url && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(url);
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${bytes}B`;
}

function attachmentMeta(attachment: VoiceAttachment): string {
  if (attachment.kind === "pdf" && attachment.mode === "excerpt") {
    return `PDF · ${attachment.pages}쪽 · 질문마다 관련 쪽 참고`;
  }
  if (attachment.kind === "pdf") return `PDF · ${attachment.pages}쪽`;
  return `이미지 · ${formatBytes(attachment.size)}`;
}

function indexMeta(attachment: VoiceAttachment): string {
  const index = attachment.index;
  if (!index) return "색인 중";
  return `색인 중 ${index.pages_done}/${index.pages}쪽`;
}

function isExcerpted(attachment: VoiceAttachment | undefined): boolean {
  return attachment?.mode === "excerpt";
}

/** Stored history carries the attachment shape of the log; the live agent uses the wire shape. */
function toSentAttachment(attachment: ChatHistoryAttachment): SentAttachment {
  return {
    chars: 0,
    id: attachment.id,
    kind: attachment.kind === "pdf" ? "pdf" : "image",
    name: attachment.name,
    pages: attachment.pages,
    size: attachment.size
  };
}

function AttachmentChips({ attachments }: { attachments: SentAttachment[] }) {
  if (!attachments.length) return null;
  return (
    <ul aria-label="첨부 파일" className="voice-attachment-list">
      {attachments.map((attachment) => (
        <li className="voice-attachment" data-kind={attachment.kind} key={attachment.id}>
          {attachment.previewUrl ? (
            // eslint-disable-next-line @next/next/no-img-element -- local object URL, not an asset
            <img alt="" className="voice-attachment-thumb" src={attachment.previewUrl} />
          ) : (
            <UiIcon
              className="voice-attachment-icon"
              name={attachment.kind === "pdf" ? "material" : "image"}
            />
          )}
          <span className="voice-attachment-name" title={attachment.name}>
            {attachment.name}
          </span>
          <span className="voice-attachment-meta">
            {attachment.mode === "excerpt" && attachment.pages_used?.length
              ? `PDF · ${attachment.pages_used.join(", ")}쪽 참고`
              : attachment.mode === "vision"
                ? `${attachment.kind === "pdf" ? "PDF" : "이미지"} · 모델이 직접 봄`
                : attachmentMeta(attachment)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function webSourceLabel(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return (
      parsed.hostname.replace(/^www\./, "") + (parsed.pathname === "/" ? "" : parsed.pathname)
    );
  } catch {
    return null;
  }
}

export function CourseAgentClient({
  courseId,
  initialSessionId = null
}: {
  courseId: string;
  /** Set when the learner reopened this conversation from 대화 이력. */
  initialSessionId?: string | null;
}) {
  const [config, setConfig] = useState<VoiceConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [chatSessionId, setChatSessionId] = useState<string | null>(initialSessionId);
  const [entries, setEntries] = useState<ChatEntry[]>([
    { kind: "message", id: 0, role: "assistant", text: GREETING, symbolState: "presence" }
  ]);
  const [question, setQuestion] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachHint, setAttachHint] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [isMuted, setIsMuted] = useState(false);
  const [isVoiceOpen, setIsVoiceOpen] = useState(false);
  const [isMicrophoneAvailable, setIsMicrophoneAvailable] = useState(true);
  const [weakConcepts, setWeakConcepts] = useState<WeakConcept[]>([]);
  const [weakConceptError, setWeakConceptError] = useState<string | null>(null);
  const [isWeakConceptLoading, setIsWeakConceptLoading] = useState(true);

  const nextId = useRef(1);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pendingAttachmentsRef = useRef<PendingAttachment[]>([]);
  // Timers of the index polls in flight, by composer item, so they stop with the item.
  const indexPollsRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const socketRef = useRef<WebSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micUnavailableRef = useRef(false);
  const captureContextRef = useRef<AudioContext | null>(null);
  const playContextRef = useRef<AudioContext | null>(null);
  const rateMismatchLoggedRef = useRef(false);
  const resampleStateRef = useRef(newResampleState());
  const pcmBufferRef = useRef<Float32Array>(new Float32Array(0));
  const pendingAudioFramesRef = useRef<string[]>([]);
  // Typed turns waiting for a live socket. The voice panel being open means the
  // student chose voice -- including the student who has no microphone and types
  // instead -- so their turn belongs to the voice agent and waits for the socket
  // rather than silently taking the typed-only path during a reconnect.
  const pendingTextRef = useRef<string[]>([]);
  const nextPlayAtRef = useRef(0);
  const activeSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const mutedRef = useRef(false);
  const voiceTurnRef = useRef<{
    tools: string[];
    latency?: number;
    pendingId?: number;
    streamStarted?: boolean;
  }>({ tools: [] });
  const lastLocalTextRef = useRef("");
  const voiceTranscriptMessageIdsRef = useRef<Map<string, number>>(new Map());
  // A dropped realtime connection used to close the panel with no explanation.
  // Retry quietly a couple of times, then say so rather than vanishing.
  const intentionalCloseRef = useRef(false);
  const reconnectsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatSessionIdRef = useRef<string | null>(initialSessionId);

  useEffect(() => {
    chatSessionIdRef.current = chatSessionId;
  }, [chatSessionId]);

  useEffect(() => {
    pendingAttachmentsRef.current = pendingAttachments;
  }, [pendingAttachments]);

  // Previews are object URLs; release whatever the composer still holds on unmount,
  // and stop asking after indexes nobody will see.
  useEffect(
    () => () => {
      pendingAttachmentsRef.current.forEach((item) => revokePreview(item.previewUrl));
      indexPollsRef.current.forEach((timer) => clearTimeout(timer));
      indexPollsRef.current.clear();
    },
    []
  );

  const allocateId = () => {
    nextId.current += 1;
    return nextId.current;
  };

  useEffect(() => {
    mutedRef.current = isMuted;
  }, [isMuted]);

  useEffect(() => {
    let isCancelled = false;
    getVoiceConfig(courseId)
      .then((value) => {
        if (!isCancelled) setConfig(value);
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setConfigError(
            error instanceof ApiError ? error.message : "AI 조교 정보를 불러오지 못했습니다."
          );
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  const loadWeakConcepts = useCallback(async () => {
    setIsWeakConceptLoading(true);
    setWeakConceptError(null);
    try {
      const result = await listWeakConcepts(courseId);
      setWeakConcepts(result.concepts);
    } catch (error) {
      setWeakConceptError(
        error instanceof ApiError ? error.message : "취약 개념을 불러오지 못했습니다."
      );
    } finally {
      setIsWeakConceptLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    let isCancelled = false;
    listWeakConcepts(courseId)
      .then((result) => {
        if (!isCancelled) setWeakConcepts(result.concepts);
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setWeakConceptError(
            error instanceof ApiError ? error.message : "취약 개념을 불러오지 못했습니다."
          );
        }
      })
      .finally(() => {
        if (!isCancelled) setIsWeakConceptLoading(false);
      });
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  // Scroll to the end for a new message, and follow an answer being written
  // only while the student is already reading the end. Trace updates change
  // neither value, so the agent's thinking never moves the transcript.
  const transcriptKey = transcriptFollowKey(entries);
  const entryCount = entries.length;
  const entryCountRef = useRef(0);
  const readingEndRef = useRef(true);

  useEffect(() => {
    const node = messagesRef.current;
    const appended = entryCount !== entryCountRef.current;
    entryCountRef.current = entryCount;
    if (node && (appended || readingEndRef.current)) node.scrollTop = node.scrollHeight;
  }, [transcriptKey, entryCount]);

  // Reopening a stored conversation replays it, then keeps answering in it.
  useEffect(() => {
    if (!initialSessionId) return;
    let isCancelled = false;

    getChatSession(initialSessionId)
      .then((detail) => {
        if (isCancelled) return;
        const replayed: ChatEntry[] = detail.logs.flatMap((log) => [
          {
            attachments: (log.attachments ?? []).map(toSentAttachment),
            kind: "message" as const,
            id: (nextId.current += 1),
            role: "user" as const,
            symbolState: "presence" as CourseAgentSymbolState,
            text: log.question
          },
          {
            kind: "message" as const,
            id: (nextId.current += 1),
            materialSources: log.sources.map(toMaterialSource),
            role: "assistant" as const,
            symbolState: "sustain" as CourseAgentSymbolState,
            text: log.answer
          }
        ]);
        if (replayed.length) setEntries((current) => [...current, ...replayed]);
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setConfigError(
          error instanceof ApiError ? error.message : "이전 대화를 불러오지 못했습니다."
        );
      });

    return () => {
      isCancelled = true;
    };
  }, [initialSessionId]);

  const appendMessage = useCallback(
    (entry: Omit<Extract<ChatEntry, { kind: "message" }>, "kind" | "id">) => {
      const id = allocateId();
      setEntries((current) => [...current, { ...entry, id, kind: "message" }]);
      return id;
    },
    []
  );

  const patchMessage = useCallback(
    (id: number, patch: Partial<Extract<ChatEntry, { kind: "message" }>>) => {
      setEntries((current) =>
        current.map((entry) =>
          entry.kind === "message" && entry.id === id ? { ...entry, ...patch } : entry
        )
      );
    },
    []
  );

  const removeMessage = useCallback((id: number) => {
    setEntries((current) =>
      current.filter((entry) => !(entry.kind === "message" && entry.id === id))
    );
  }, []);

  const patchTrace = useCallback((id: number, update: (trace: TurnTrace) => TurnTrace) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.kind === "message" && entry.id === id
          ? { ...entry, trace: update(entry.trace ?? EMPTY_TRACE) }
          : entry
      )
    );
  }, []);

  // ---------------------------------------------------------------- attachments

  const addFiles = useCallback(
    (files: File[]) => {
      if (!files.length) return;
      const attachable = files.filter(isAttachable);
      const room = Math.max(0, MAX_ATTACHMENTS - pendingAttachmentsRef.current.length);
      const accepted = attachable.slice(0, room);
      if (attachable.length < files.length) {
        setAttachHint(ATTACHMENT_HINT_TYPES);
      } else if (accepted.length < attachable.length) {
        setAttachHint(`파일은 한 번에 ${MAX_ATTACHMENTS}개까지 첨부할 수 있어요.`);
      } else {
        setAttachHint(null);
      }
      if (!accepted.length) return;

      const items: PendingAttachment[] = accepted.map((file) => ({
        file,
        localId: allocateId(),
        previewUrl: previewUrlFor(file),
        status: "uploading"
      }));
      setPendingAttachments((current) => [...current, ...items]);

      const patchItem = (localId: number, patch: Partial<PendingAttachment>) => {
        setPendingAttachments((current) =>
          current.map((entry) => (entry.localId === localId ? { ...entry, ...patch } : entry))
        );
      };

      // A long PDF is indexed after upload; ask how far it is until it is ready.
      const pollIndex = (localId: number, attachmentId: string) => {
        const timer = setTimeout(() => {
          indexPollsRef.current.delete(localId);
          if (!pendingAttachmentsRef.current.some((entry) => entry.localId === localId)) return;
          getVoiceAttachment(courseId, attachmentId)
            .then((attachment) => {
              if (attachment.index?.status === "ready" || !attachment.index) {
                patchItem(localId, { attachment, status: "ready" });
              } else if (attachment.index.status === "failed") {
                patchItem(localId, {
                  attachment,
                  error: attachment.index.message || "파일을 색인하지 못했어요",
                  status: "error"
                });
              } else {
                patchItem(localId, { attachment });
                pollIndex(localId, attachmentId);
              }
            })
            .catch(() => pollIndex(localId, attachmentId));
        }, INDEX_POLL_MS);
        indexPollsRef.current.set(localId, timer);
      };

      items.forEach((item) => {
        uploadVoiceAttachment(courseId, item.file)
          .then((attachment) => {
            if (attachment.index && attachment.index.status !== "ready") {
              if (attachment.index.status === "failed") {
                patchItem(item.localId, {
                  attachment,
                  error: attachment.index.message || "파일을 색인하지 못했어요",
                  status: "error"
                });
                return;
              }
              patchItem(item.localId, { attachment, status: "indexing" });
              pollIndex(item.localId, attachment.id);
              return;
            }
            patchItem(item.localId, { attachment, status: "ready" });
          })
          .catch((error: unknown) => {
            setPendingAttachments((current) =>
              current.map((entry) =>
                entry.localId === item.localId
                  ? {
                      ...entry,
                      error:
                        error instanceof ApiError && error.status === 413
                          ? "파일이 너무 커요"
                          : error instanceof ApiError
                            ? error.message
                            : "업로드하지 못했어요",
                      status: "error"
                    }
                  : entry
              )
            );
          });
      });
    },
    [courseId]
  );

  const removeAttachment = useCallback(
    (localId: number) => {
      const item = pendingAttachmentsRef.current.find((entry) => entry.localId === localId);
      if (!item) return;
      const poll = indexPollsRef.current.get(localId);
      if (poll) {
        clearTimeout(poll);
        indexPollsRef.current.delete(localId);
      }
      revokePreview(item.previewUrl);
      if (item.attachment) {
        void deleteVoiceAttachment(courseId, item.attachment.id).catch(() => undefined);
      }
      setPendingAttachments((current) => current.filter((entry) => entry.localId !== localId));
      setAttachHint(null);
    },
    [courseId]
  );

  /** Forget every file in the composer, on the server too. */
  const clearAttachments = useCallback(() => {
    indexPollsRef.current.forEach((timer) => clearTimeout(timer));
    indexPollsRef.current.clear();
    pendingAttachmentsRef.current.forEach((item) => {
      revokePreview(item.previewUrl);
      if (item.attachment) {
        void deleteVoiceAttachment(courseId, item.attachment.id).catch(() => undefined);
      }
    });
    setPendingAttachments([]);
    setAttachHint(null);
  }, [courseId]);

  const handleFileInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  };

  const handlePaste = (event: React.ClipboardEvent<HTMLInputElement>) => {
    const files = Array.from(event.clipboardData?.files ?? []);
    if (!files.length || isVoiceOpen) return;
    event.preventDefault();
    addFiles(files);
  };

  // Drops are always claimed: an unhandled drop makes the browser navigate the
  // tab to the file. While the voice panel is open the files are simply ignored.
  const handleDragOver = (event: React.DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isVoiceOpen && !isSending) setIsDragging(true);
  };

  const handleDragLeave = (event: React.DragEvent<HTMLFormElement>) => {
    // Crossing into a child fires leave on the form; only a real exit ends the outline.
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget.contains(next)) return;
    setIsDragging(false);
  };

  const handleDrop = (event: React.DragEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsDragging(false);
    if (isVoiceOpen || isSending) return;
    addFiles(Array.from(event.dataTransfer?.files ?? []));
  };

  /**
   * Drop what a dead turn left behind. A bubble holding only the progress notice
   * has nothing to show for the turn and goes away; one that already holds the
   * answer keeps it. The reset matters more than the bubble: a stale pendingId is
   * what the *next* turn's notice and transcript patch, which renders the next
   * answer above its own question.
   */
  const endPendingTurn = useCallback(() => {
    const turn = voiceTurnRef.current;
    if (turn.pendingId !== undefined && !turn.streamStarted) {
      removeMessage(turn.pendingId);
    }
    voiceTurnRef.current = { tools: [] };
    setIsSending(false);
  }, [removeMessage]);

  const appendVisualizations = useCallback((visualizations: VoiceVisualization[]) => {
    if (!visualizations.length) return;
    setEntries((current) => [
      ...current,
      ...visualizations.map((visualization) => ({
        kind: "visualization" as const,
        id: allocateId(),
        visualization
      }))
    ]);
  }, []);

  // ---------------------------------------------------------------- text chat

  const isUploading = pendingAttachments.some(
    (item) => item.status === "uploading" || item.status === "indexing"
  );
  const isIndexing = pendingAttachments.some((item) => item.status === "indexing");
  const hasPinned = pendingAttachments.some((item) => isExcerpted(item.attachment));
  const readyAttachments = pendingAttachments.filter(
    (item): item is PendingAttachment & { attachment: VoiceAttachment } =>
      item.status === "ready" && item.attachment !== undefined
  );

  // A typed turn on the voice path carries no files, so an upload in flight
  // only holds back a typed-only turn.
  const waitingForUpload = isUploading && !isVoiceOpen;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || isSending || waitingForUpload) return;

    // A voice turn is spoken and heard, so a file cannot ride on it: while the
    // panel is open the files stay in the composer for the next typed-only turn.
    const sending = isVoiceOpen ? [] : readyAttachments;
    const sentAttachments: SentAttachment[] = sending.map((item) => ({
      ...item.attachment,
      previewUrl: item.previewUrl
    }));
    const questionId = appendMessage({
      attachments: sentAttachments,
      role: "user",
      symbolState: "presence",
      text
    });
    // On the typed path the folded "생각 중…" line carries the waiting; the bubble
    // stays empty until the progress notice or the first token fills it.
    const pendingId = appendMessage({
      role: "assistant",
      symbolState: "flow",
      text: isVoiceOpen ? "답변을 준비하고 있습니다." : "",
      trace: isVoiceOpen ? undefined : startTrace()
    });
    setQuestion("");
    setIsSending(true);
    if (sending.length) {
      // The previews now belong to the sent message; the failed ones are dropped.
      // A long PDF read by excerpt stays pinned, so the next question can look
      // things up in it too; everything else was consumed by this turn.
      pendingAttachments
        .filter((item) => item.status !== "ready")
        .forEach((item) => revokePreview(item.previewUrl));
      setPendingAttachments((current) =>
        current
          .filter((item) => item.status === "ready" && isExcerpted(item.attachment))
          .map((item) => ({ ...item, pinned: true }))
      );
      setAttachHint(null);
    }

    const liveSocket = socketRef.current;
    if (isVoiceOpen) {
      // Submitting a turn interrupts the agent, exactly as speaking over it does.
      // Only a spoken barge-in gets a server "flush", so without this the agent
      // talks through its previous answer first -- and typing is the whole way a
      // student with no microphone interrupts. Done locally because the client
      // starts the turn and need not wait for a round trip to stop the audio.
      flushPlayback();
      lastLocalTextRef.current = text.toLocaleLowerCase().trim().replace(/\s+/g, " ");
      voiceTurnRef.current = {
        pendingId,
        streamStarted: false,
        tools: []
      };
      setVoiceState("thinking");
      const payload = JSON.stringify({ type: "text", text });
      if (liveSocket?.readyState === WebSocket.OPEN) {
        liveSocket.send(payload);
      } else {
        pendingTextRef.current.push(payload);
      }
      return;
    }

    let streamed = "";
    try {
      const answer: VoiceAnswer = await streamVoiceAnswer(
        courseId,
        {
          attachment_ids: sending.map((item) => item.attachment.id),
          chat_session_id: chatSessionId,
          mode: "socratic",
          text
        },
        {
          onStatus: (message) => {
            if (!streamed) {
              patchMessage(pendingId, { text: message, symbolState: "flow" });
            }
          },
          onStep: (step: VoiceTraceStep) => {
            patchTrace(pendingId, (trace) => ({ ...trace, steps: upsertStep(trace.steps, step) }));
          },
          onThinking: (text, stepKey) => {
            patchTrace(pendingId, (trace) => appendThinking(trace, text, stepKey));
          },
          onThought: (text, stepKey) => {
            patchTrace(pendingId, (trace) => appendThought(trace, text, stepKey));
          },
          onRewind: () => {
            // A discarded draft: what streamed so far leaves the bubble.
            streamed = "";
            patchMessage(pendingId, { text: "", symbolState: "flow" });
          },
          onToken: (token) => {
            streamed += token;
            patchMessage(pendingId, { text: streamed, symbolState: "flow" });
          }
        }
      );
      setChatSessionId(answer.session_id);
      patchTrace(pendingId, finishTrace);
      if (sentAttachments.length) {
        // The turn says what it read from each file (an excerpted PDF: which pages).
        patchMessage(questionId, {
          attachments: sentAttachments.map((sent) => {
            const read = answer.attachments.find((item) => item.id === sent.id);
            return read ? { ...sent, ...read, index: undefined } : sent;
          })
        });
      }
      patchMessage(pendingId, {
        materialSources: answer.material_sources,
        symbolState: "bloom",
        text: answer.reply,
        timing:
          answer.timings.total !== undefined ? `응답 ${answer.timings.total}ms` : undefined,
        tools: answer.tools,
        webSources: answer.sources
      });
      appendVisualizations(answer.visualizations);
    } catch (error) {
      patchTrace(pendingId, failTrace);
      patchMessage(pendingId, {
        symbolState: "error",
        text: `오류: ${error instanceof Error ? error.message : "답변을 생성하지 못했습니다."}`
      });
    } finally {
      setIsSending(false);
    }
  };

  const toggleTrace = (id: number) => {
    patchTrace(id, (trace) => ({ ...trace, open: !trace.open }));
  };

  const handleNewChat = async () => {
    if (isVoiceOpen) stopVoice();
    clearAttachments();
    // The sent messages' image previews go with the conversation they belonged to.
    entries.forEach((entry) => {
      if (entry.kind === "message") {
        entry.attachments?.forEach((attachment) => revokePreview(attachment.previewUrl));
      }
    });
    await resetVoiceConversation(courseId).catch(() => undefined);
    nextId.current = 1;
    setChatSessionId(null);
    setEntries([
      { kind: "message", id: 0, role: "assistant", text: GREETING, symbolState: "presence" }
    ]);
  };

  // -------------------------------------------------------------- voice audio

  const flushPlayback = useCallback(() => {
    activeSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
    });
    activeSourcesRef.current.clear();
    nextPlayAtRef.current = 0;
    // The discarded answer's last sample is not the next one's left neighbour.
    resampleStateRef.current = newResampleState();
  }, []);

  const playChunk = useCallback((bytes: Uint8Array, rate: number) => {
    const context = playContextRef.current;
    if (!context) return;
    const pcm = decodePcm16(bytes);
    if (!pcm) return;
    if (rate !== context.sampleRate && !rateMismatchLoggedRef.current) {
      rateMismatchLoggedRef.current = true;
      console.warn(
        `[voice] playback context is ${context.sampleRate} Hz but audio is ${rate} Hz; ` +
          "resampling to the context rate across chunk boundaries"
      );
    }
    // Resampled here rather than by handing the browser a buffer at the wrong
    // rate: it would resample each chunk on its own, and the discontinuity left
    // at every boundary is audible as a tick through the whole answer.
    const samples = resample(pcm, rate, context.sampleRate, resampleStateRef.current);
    if (samples.length === 0) return;
    const buffer = context.createBuffer(1, samples.length, context.sampleRate);
    buffer.getChannelData(0).set(samples);

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    // The first TTS request of a turn delivers ~320ms of audio and the packet
    // after it can land 60-80ms late, so a 30ms lead under-runs audibly right as
    // the agent starts speaking. Give the first chunk a real jitter buffer and let
    // later chunks, which play from a buffer several seconds deep, stay tight.
    const lead = nextPlayAtRef.current === 0 ? 0.18 : 0.03;
    const startAt = Math.max(context.currentTime + lead, nextPlayAtRef.current);
    source.start(startAt);
    nextPlayAtRef.current = startAt + buffer.duration;
    activeSourcesRef.current.add(source);
    source.onended = () => activeSourcesRef.current.delete(source);
  }, []);

  const handleSocketMessage = useCallback(
    (raw: MessageEvent<string>) => {
      const message = JSON.parse(raw.data) as Record<string, unknown>;
      const type = String(message.type ?? "");

      if (type === "ready") {
        if (typeof message.session_id === "string") setChatSessionId(message.session_id);
        setVoiceState("listening");
      } else if (type === "state") {
        const next = String(message.value) as VoiceState;
        setVoiceState(next);
      } else if (type === "flush") {
        flushPlayback();
        // Barge-in cancels the turn server-side, so nothing will ever patch its
        // bubble. Before the progress notice existed there was no bubble yet to
        // strand, because a spoken turn only created one on its first token.
        endPendingTurn();
      } else if (type === "token") {
        const token = String(message.text ?? "");
        const turn = voiceTurnRef.current;
        if (turn.pendingId === undefined) {
          turn.pendingId = appendMessage({
            role: "assistant",
            text: token,
            symbolState: "flow"
          });
          turn.streamStarted = true;
        } else if (!turn.streamStarted) {
          patchMessage(turn.pendingId, { text: token, symbolState: "flow" });
          turn.streamStarted = true;
        } else {
          setEntries((current) =>
            current.map((entry) =>
              entry.kind === "message" && entry.id === turn.pendingId
                ? { ...entry, text: entry.text + token }
                : entry
            )
          );
        }
      } else if (type === "filler") {
        const text = String(message.text ?? "").trim();
        if (text) {
          const turn = voiceTurnRef.current;
          if (message.transient) {
            // A fixed progress notice, not something the agent decided to say:
            // keep it in the pending bubble so the answer replaces it instead of
            // leaving an identical line in the transcript every turn.
            if (turn.pendingId === undefined) {
              turn.pendingId = appendMessage({
                role: "assistant",
                text,
                symbolState: "resonance"
              });
            } else {
              patchMessage(turn.pendingId, { text, symbolState: "resonance" });
            }
            turn.streamStarted = false;
          } else if (turn.pendingId === undefined) {
            appendMessage({ role: "assistant", text, symbolState: "resonance" });
          } else {
            patchMessage(turn.pendingId, { text, symbolState: "resonance" });
            turn.pendingId = undefined;
            turn.streamStarted = false;
          }
        }
      } else if (type === "text_boundary") {
        const turn = voiceTurnRef.current;
        if (turn.pendingId !== undefined) {
          patchMessage(turn.pendingId, { symbolState: "resonance" });
          turn.pendingId = undefined;
          turn.streamStarted = false;
        }
      } else if (type === "transcript") {
        const text = String(message.text ?? "");
        if (message.who === "user") {
          const transcriptId = String(message.item_id ?? "");
          const existingId = transcriptId
            ? voiceTranscriptMessageIdsRef.current.get(transcriptId)
            : undefined;
          const normalized = text.toLocaleLowerCase().trim().replace(/\s+/g, " ");
          if (existingId !== undefined) {
            patchMessage(existingId, { text });
          } else if (normalized !== lastLocalTextRef.current) {
            const messageId = appendMessage({ role: "user", text, symbolState: "presence" });
            if (transcriptId) {
              voiceTranscriptMessageIdsRef.current.set(transcriptId, messageId);
            }
          }
          lastLocalTextRef.current = "";
        } else {
          const turn = voiceTurnRef.current;
          const patch = {
            symbolState: "bloom" as CourseAgentSymbolState,
            text,
            timing: turn.latency === undefined ? undefined : `첫 음성 ${turn.latency}ms`,
            tools: turn.tools
          };
          if (turn.pendingId === undefined) {
            appendMessage({ role: "assistant", ...patch });
          } else {
            patchMessage(turn.pendingId, patch);
          }
          voiceTurnRef.current = { tools: [] };
        }
      } else if (type === "turn_done") {
        setIsSending(false);
      } else if (type === "tool") {
        voiceTurnRef.current.tools.push(String(message.name ?? ""));
      } else if (type === "visualization") {
        appendVisualizations([message.visualization as VoiceVisualization]);
      } else if (type === "visualization_error") {
        appendMessage({
          role: "assistant",
          symbolState: "error",
          text: String(message.message ?? "시각 자료를 표시하지 못했습니다.")
        });
      } else if (type === "latency") {
        voiceTurnRef.current.latency = Number(message.ms);
      } else if (type === "audio") {
        playChunk(fromBase64(String(message.data ?? "")), Number(message.rate ?? 24000));
      } else if (type === "error") {
        endPendingTurn();
        appendMessage({
          role: "assistant",
          symbolState: "error",
          text: `오류: ${String(message.message ?? "")}`
        });
        setVoiceState("listening");
        setIsSending(false);
      }
    },
    [appendMessage, appendVisualizations, endPendingTurn, flushPlayback, patchMessage, playChunk]
  );

  const sendSamples = useCallback((block: Float32Array) => {
    const socket = socketRef.current;
    if (mutedRef.current) return;

    const joined = new Float32Array(pcmBufferRef.current.length + block.length);
    joined.set(pcmBufferRef.current);
    joined.set(block, pcmBufferRef.current.length);
    pcmBufferRef.current = joined;

    while (pcmBufferRef.current.length >= FRAME_SAMPLES) {
      const frame = pcmBufferRef.current.subarray(0, FRAME_SAMPLES);
      pcmBufferRef.current = pcmBufferRef.current.slice(FRAME_SAMPLES);
      const int16 = new Int16Array(FRAME_SAMPLES);
      for (let index = 0; index < FRAME_SAMPLES; index += 1) {
        const sample = Math.max(-1, Math.min(1, frame[index]));
        int16[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
      const payload = JSON.stringify({
        data: toBase64(new Uint8Array(int16.buffer)),
        type: "audio"
      });
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(payload);
      } else if (!socket || socket.readyState === WebSocket.CONNECTING) {
        pendingAudioFramesRef.current.push(payload);
        if (pendingAudioFramesRef.current.length > MAX_PENDING_AUDIO_FRAMES) {
          pendingAudioFramesRef.current.shift();
        }
      }
    }
  }, []);

  const stopVoice = useCallback(() => {
    intentionalCloseRef.current = true;
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectsRef.current = 0;
    flushPlayback();
    socketRef.current?.close();
    micStreamRef.current?.getTracks().forEach((track) => track.stop());
    void captureContextRef.current?.close();
    void playContextRef.current?.close();
    socketRef.current = null;
    micStreamRef.current = null;
    micUnavailableRef.current = false;
    captureContextRef.current = null;
    playContextRef.current = null;
    pcmBufferRef.current = new Float32Array(0);
    pendingAudioFramesRef.current = [];
    pendingTextRef.current = [];
    voiceTurnRef.current = { tools: [] };
    voiceTranscriptMessageIdsRef.current.clear();
    setIsVoiceOpen(false);
    setIsMicrophoneAvailable(true);
    setIsMuted(false);
    setIsSending(false);
    setVoiceState("idle");
  }, [flushPlayback]);

  useEffect(() => stopVoice, [stopVoice]);

  /**
   * End a turn the socket took with it. The server cancels the turn when the
   * connection closes and nothing replays it, so whatever bubble is pending will
   * never be patched by an answer. A queued turn is the exception: it was never
   * sent, so the reconnect will send it and its bubble is still live.
   */
  function failPendingTurn(text: string) {
    if (pendingTextRef.current.length) return;
    const turn = voiceTurnRef.current;
    if (turn.pendingId !== undefined && !turn.streamStarted) {
      patchMessage(turn.pendingId, { symbolState: "error", text });
    }
    voiceTurnRef.current = { tools: [] };
    setIsSending(false);
  }

  function openVoiceSocket(): WebSocket {
    const socket = new WebSocket(voiceStreamUrl(courseId, chatSessionIdRef.current));
    socket.onopen = () => {
      reconnectsRef.current = 0;
      pendingAudioFramesRef.current.forEach((payload) => socket.send(payload));
      pendingAudioFramesRef.current = [];
      pendingTextRef.current.forEach((payload) => socket.send(payload));
      pendingTextRef.current = [];
    };
    socket.onmessage = handleSocketMessage;
    // A socket error is always followed by a close, so one recovery path is enough.
    socket.onerror = () => undefined;
    socket.onclose = () => {
      socketRef.current = null;
      if (intentionalCloseRef.current) return;
      flushPlayback();
      const attempt = reconnectsRef.current;
      // Even a reconnect that succeeds does not revive the turn that was in
      // flight, and its pending bubble would otherwise sit on "질문을 살펴보고
      // 있어요..." forever -- then swallow the *next* turn's answer, because the
      // stale pendingId is still what the next filler and transcript patch.
      failPendingTurn("연결이 끊겨 답변이 중단됐어요. 다시 질문해 주세요.");
      if (attempt >= RECONNECT_DELAYS_MS.length) {
        appendMessage({
          role: "assistant",
          symbolState: "error",
          text: "음성 연결이 끊어졌어요. 마이크 버튼을 다시 눌러 대화를 이어가 주세요."
        });
        stopVoice();
        return;
      }
      reconnectsRef.current = attempt + 1;
      setVoiceState("connecting");
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null;
        socketRef.current = openVoiceSocket();
      }, RECONNECT_DELAYS_MS[attempt]);
    };
    return socket;
  }

  const startVoice = async () => {
    micUnavailableRef.current = false;
    intentionalCloseRef.current = false;
    reconnectsRef.current = 0;
    setIsMicrophoneAvailable(true);
    setIsVoiceOpen(true);
    setVoiceState("connecting");

    try {
      const playContext = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE });
      void playContext.resume().catch(() => undefined);
      playContextRef.current = playContext;
      nextPlayAtRef.current = 0;

      socketRef.current = openVoiceSocket();
    } catch (error) {
      setIsVoiceOpen(false);
      setVoiceState("idle");
      return;
    }

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("사용 가능한 마이크 장치가 없습니다.");
      }
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: { autoGainControl: true, echoCancellation: true, noiseSuppression: true }
      });
      micStreamRef.current = micStream;

      const captureContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      if (captureContext.sampleRate !== SAMPLE_RATE) {
        throw new Error("Chrome 또는 Edge에서 실행해 주세요.");
      }
      captureContextRef.current = captureContext;
      await captureContext.audioWorklet.addModule("/voice-worklet.js");
      const source = captureContext.createMediaStreamSource(micStream);
      const capture = new AudioWorkletNode(captureContext, "pcm-capture");
      source.connect(capture);
      capture.port.onmessage = (event: MessageEvent<Float32Array>) => sendSamples(event.data);
    } catch {
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
      void captureContextRef.current?.close();
      micStreamRef.current = null;
      captureContextRef.current = null;
      micUnavailableRef.current = true;
      setIsMicrophoneAvailable(false);
      setVoiceState("listening");
    }
  };

  // ------------------------------------------------------------------ render

  const voiceReady = config?.voice_enabled ?? false;
  // The panel shows one line at rest, so it has to carry whichever of these
  // applies rather than stacking a pill, a status and a hint.
  const voiceHelp = !voiceReady
    ? "음성 기능이 아직 준비되지 않았습니다. 텍스트 질문은 그대로 사용할 수 있습니다."
    : isMicrophoneAvailable
      ? "마이크로 질문하면 음성으로 답해요. 한 번 시작하면 버튼 없이 이어서 대화합니다."
      : "마이크를 사용할 수 없습니다. 텍스트 질문은 그대로 사용할 수 있습니다.";

  return (
    <section className="course-agent-page">
      <div className="icampus-breadcrumb">
        과목 &gt; {config?.course_name ?? "강의"} &gt; <b>COURSE AGENT</b>
      </div>

      <div className="icampus-page-heading">
        <div>
          <h1>COURSE AGENT</h1>
          <p>강의자료를 근거로 함께 답을 찾아가는 AI 음성 조교</p>
        </div>
        <span className="icampus-term-badge">학습자 화면</span>
      </div>

      <div className="icampus-notice">
        AI 답변은 강의자료의 파일명과 페이지를 근거로 제공합니다. 중요한 내용은 담당 교수자의
        안내와 원문을 함께 확인하세요.
      </div>

      {configError ? (
        <p className="admin-alert" role="alert">
          {configError}
        </p>
      ) : null}
      {config && !config.is_search_ready ? (
        <p className="admin-alert" role="status">
          아직 처리된 강의자료가 없어 강의자료 근거가 부족할 수 있습니다.
        </p>
      ) : null}

      <div className="voice-chat-layout">
        <section aria-label="AI 조교 채팅" className="icampus-card voice-chat-card">
          <div className="icampus-card-head">
            <div className="voice-agent-title">
              <CourseAgentSymbol size={32} state="presence" />
              <h2>{config?.course_name ?? "강의"} AI 조교</h2>
            </div>
            <small className="voice-online">● 이용 가능</small>
          </div>
          <div className="voice-chat-toolbar">
            <span>질문과 힌트로 함께 생각해요</span>
            <button className="voice-secondary" onClick={handleNewChat} type="button">
              새 대화
            </button>
          </div>
          <div
            aria-live="polite"
            className="voice-messages"
            onScroll={(event) => {
              const node = event.currentTarget;
              readingEndRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 24;
            }}
            ref={messagesRef}
          >
            {entries.map((entry) =>
              entry.kind === "visualization" ? (
                <CourseAgentVisualizationCard
                  courseId={courseId}
                  key={entry.id}
                  visualization={entry.visualization}
                />
              ) : (
                <div className="voice-message" data-role={entry.role} key={entry.id}>
                  <div className="voice-avatar">
                    {entry.role === "user" ? (
                      "나"
                    ) : (
                      <CourseAgentSymbol
                        animated
                        label={`Course Agent ${entry.symbolState}`}
                        size={34}
                        state={entry.symbolState}
                      />
                    )}
                  </div>
                  <div className="voice-bubble-wrap">
                    <div className="voice-who">
                      {entry.role === "user" ? "나" : "COURSE AGENT"}
                    </div>
                    {entry.attachments?.length ? (
                      <AttachmentChips attachments={entry.attachments} />
                    ) : null}
                    {entry.trace ? (
                      <CourseAgentTrace
                        onToggle={() => toggleTrace(entry.id)}
                        trace={entry.trace}
                      />
                    ) : null}
                    {entry.text ? <MathText text={entry.text} /> : null}
                    {entry.tools?.length ? (
                      <div className="voice-tool-row">
                        {entry.tools.map((tool, index) => (
                          <span className="voice-tool-chip" key={`${tool}-${index}`}>
                            {tool}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {entry.materialSources?.length || entry.webSources?.length ? (
                      <div className="voice-source-list">
                        <div className="voice-source-title">참고 출처</div>
                        {entry.materialSources?.map((source, index) => (
                          <span className="voice-source-item" key={`${source.material_id}-${index}`}>
                            {index + 1}. {sourceLabel(source)}
                          </span>
                        ))}
                        {entry.webSources?.map((url, index) => {
                          const label = webSourceLabel(url);
                          if (!label) return null;
                          return (
                            <a
                              className="voice-source-link"
                              href={url}
                              key={url}
                              rel="noopener noreferrer"
                              target="_blank"
                              title={url}
                            >
                              {(entry.materialSources?.length ?? 0) + index + 1}. {label}
                            </a>
                          );
                        })}
                      </div>
                    ) : null}
                    {entry.timing ? <div className="voice-timing">{entry.timing}</div> : null}
                  </div>
                </div>
              )
            )}
          </div>
          <form
            className="voice-chat-form"
            data-dragging={isDragging}
            onDragLeave={handleDragLeave}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            onSubmit={handleSubmit}
          >
            {pendingAttachments.length ? (
              <ul aria-label="첨부할 파일" className="voice-attach-list">
                {pendingAttachments.map((item) => (
                  <li
                    className="voice-attach-chip"
                    data-pinned={item.pinned ? "true" : undefined}
                    data-status={item.status}
                    key={item.localId}
                  >
                    {item.previewUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element -- local object URL
                      <img alt="" className="voice-attach-thumb" src={item.previewUrl} />
                    ) : (
                      <UiIcon
                        className="voice-attach-icon"
                        name={item.file.type === "application/pdf" || /\.pdf$/i.test(item.file.name)
                          ? "material"
                          : "image"}
                      />
                    )}
                    <span className="voice-attach-text">
                      <span className="voice-attach-name" title={item.file.name}>
                        {item.file.name}
                      </span>
                      <span className="voice-attach-meta">
                        {item.status === "uploading"
                          ? "업로드 중"
                          : item.status === "indexing" && item.attachment
                            ? indexMeta(item.attachment)
                            : item.status === "error"
                              ? item.error
                              : item.attachment
                                ? `${item.pinned ? "대화에 유지 · " : ""}${attachmentMeta(item.attachment)}`
                                : ""}
                      </span>
                    </span>
                    <button
                      aria-label={`${item.file.name} 첨부 취소`}
                      className="voice-attach-remove"
                      onClick={() => removeAttachment(item.localId)}
                      type="button"
                    >
                      <UiIcon name="close" />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            {attachHint ? (
              <p className="voice-attach-hint" role="status">
                {attachHint}
              </p>
            ) : isVoiceOpen && pendingAttachments.length ? (
              <p className="voice-attach-hint" role="status">
                음성 대화 중에는 첨부 파일을 보낼 수 없어요. 음성 대화를 종료한 뒤 전송해 주세요.
              </p>
            ) : isIndexing ? (
              <p className="voice-attach-hint" role="status">
                긴 PDF를 색인하고 있어요. 끝나면 질문마다 관련 쪽을 찾아 참고해요.
              </p>
            ) : hasPinned ? (
              <p className="voice-attach-hint" role="status">
                긴 PDF는 대화에 남아 질문마다 관련 쪽만 찾아 참고해요. ×로 빼면 참고를 멈춰요.
              </p>
            ) : null}
            <div className="voice-chat-form-row">
              <input
                accept="image/*,.pdf,application/pdf"
                aria-label="첨부할 파일 선택"
                hidden
                multiple
                onChange={handleFileInput}
                ref={fileInputRef}
                type="file"
              />
              <button
                aria-label="파일 첨부"
                className="voice-attach-button"
                disabled={isVoiceOpen || isSending || pendingAttachments.length >= MAX_ATTACHMENTS}
                onClick={() => fileInputRef.current?.click()}
                title={
                  isVoiceOpen
                    ? "음성 대화 중에는 파일을 첨부할 수 없어요"
                    : "이미지 또는 PDF 첨부"
                }
                type="button"
              >
                <UiIcon name="attachment" />
              </button>
              <input
                aria-label="AI 조교에게 질문"
                autoComplete="off"
                disabled={isSending}
                maxLength={4000}
                onChange={(event) => setQuestion(event.target.value)}
                onPaste={handlePaste}
                placeholder={
                  pendingAttachments.length
                    ? "첨부한 파일에 대해 무엇을 물어볼까요?"
                    : "예: 강의자료에서 정상성과 차분의 관계를 찾아 설명해줘"
                }
                value={question}
              />
              <button
                className="voice-primary"
                disabled={isSending || waitingForUpload}
                title={
                  waitingForUpload
                    ? isIndexing
                      ? "PDF 색인이 끝나면 보낼 수 있어요"
                      : "파일 업로드가 끝나면 보낼 수 있어요"
                    : undefined
                }
                type="submit"
              >
                전송
              </button>
            </div>
          </form>
        </section>

        <aside className="icampus-card voice-panel">
          <div className="icampus-card-head">
            <h2>음성으로 질문</h2>
          </div>
          <div
            className="icampus-card-body voice-stage"
            data-muted={isMuted}
            data-open={isVoiceOpen}
            data-ready={voiceReady}
            data-state={voiceState}
          >
            <button
              aria-label={isVoiceOpen ? "음성 대화 진행 중" : "음성으로 질문하기"}
              className="voice-orb"
              data-state={voiceState}
              disabled={isVoiceOpen || !voiceReady}
              onClick={startVoice}
              type="button"
            >
              <span aria-hidden="true" className="voice-orb-ripple" />
              <span aria-hidden="true" className="voice-orb-ripple voice-orb-ripple--late" />
              <span aria-hidden="true" className="voice-orb-body" />
              <span className="voice-orb-face">
                {!isVoiceOpen ? (
                  <>
                    <UiIcon className="voice-orb-mic" name="mic" />
                    <span className="voice-orb-label">음성 시작</span>
                  </>
                ) : isMicrophoneAvailable ? (
                  <span aria-hidden="true" className="voice-level" data-state={voiceState}>
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                ) : (
                  // Nothing is being heard without a microphone, so a level meter
                  // would be claiming activity that is not happening.
                  <span className="voice-orb-label">대화 중</span>
                )}
              </span>
            </button>
            <div aria-live="polite" className="voice-state">
              {!isVoiceOpen
                ? voiceReady
                  ? "대기 중"
                  : "사용할 수 없음"
                : !isMicrophoneAvailable
                  ? "마이크 없음 · 채팅창에 입력해 대화하세요"
                  : isMuted
                    ? "마이크 꺼짐"
                    : VOICE_STATE_CAPTIONS[voiceState]}
            </div>
            {isVoiceOpen ? (
              <div className="voice-controls voice-call-controls">
                {isMicrophoneAvailable ? (
                  <button
                    aria-label={isMuted ? "마이크 켜기" : "마이크 끄기"}
                    aria-pressed={isMuted}
                    className="voice-round-button"
                    data-variant="mic"
                    onClick={() => setIsMuted((muted) => !muted)}
                    title={isMuted ? "마이크 켜기" : "마이크 끄기"}
                    type="button"
                  >
                    <UiIcon name={isMuted ? "mic-off" : "mic"} />
                  </button>
                ) : null}
                <button
                  aria-label="음성 대화 종료"
                  className="voice-round-button"
                  data-variant="end"
                  onClick={stopVoice}
                  title="음성 대화 종료"
                  type="button"
                >
                  <UiIcon name="close" />
                </button>
              </div>
            ) : (
              <p className="voice-help">{voiceHelp}</p>
            )}
          </div>
        </aside>
      </div>

      {config?.can_manage === false ? (
        <section aria-labelledby="weak-concepts-title" className="icampus-card weak-concepts-card">
        <div className="icampus-card-head">
          <div>
            <h2 id="weak-concepts-title">내 취약 개념</h2>
            <small>COURSE AGENT가 대화에서 발견한 현재 과목의 학습 포인트입니다.</small>
          </div>
          <button
            className="voice-secondary"
            disabled={isWeakConceptLoading}
            onClick={() => void loadWeakConcepts()}
            type="button"
          >
            {isWeakConceptLoading ? "불러오는 중" : "새로고침"}
          </button>
        </div>
        <div className="icampus-card-body">
          {weakConceptError ? (
            <p className="admin-alert" role="alert">
              {weakConceptError}
            </p>
          ) : null}
          {!weakConceptError && isWeakConceptLoading && weakConcepts.length === 0 ? (
            <p className="voice-empty">취약 개념을 불러오는 중입니다.</p>
          ) : null}
          {!weakConceptError && !isWeakConceptLoading && weakConcepts.length === 0 ? (
            <p className="voice-empty">아직 저장된 취약 개념이 없습니다.</p>
          ) : null}
          {weakConcepts.length > 0 ? (
            <div className="weak-concept-list">
              {weakConcepts.map((item) => (
                <article className="weak-concept-item" key={item.memory_id}>
                  <div className="weak-concept-head">
                    <h3>{item.concept}</h3>
                    <span className="icampus-term-badge">
                      {WEAK_CONCEPT_STATUS_LABELS[item.status]}
                    </span>
                  </div>
                  <p>{item.difficulty_note}</p>
                  <div className="weak-mastery-row">
                    <div
                      aria-label={`${item.concept} 이해도`}
                      aria-valuemax={100}
                      aria-valuemin={0}
                      aria-valuenow={item.mastery_percent}
                      className="weak-mastery-track"
                      role="progressbar"
                    >
                      <span style={{ width: `${item.mastery_percent}%` }} />
                    </div>
                    <strong>{item.mastery_percent}%</strong>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </div>
        </section>
      ) : null}
    </section>
  );
}
