"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getChatSession } from "../../lib/api";
import type { AnswerSource } from "../../lib/api";
import type {
  VoiceAnswer,
  VoiceConfig,
  VoiceMaterialSource,
  VoiceVisualization,
  WeakConcept
} from "../../lib/voice-api";
import {
  getVoiceConfig,
  listWeakConcepts,
  resetVoiceConversation,
  streamVoiceAnswer,
  voiceStreamUrl
} from "../../lib/voice-api";
import { UiIcon } from "../ui/ui-icon";
import { CourseAgentSymbol } from "../ui/course-agent-symbol";
import type { CourseAgentSymbolState } from "../ui/course-agent-symbol";
import { CourseAgentVisualizationCard } from "./course-agent-visualization";

const SAMPLE_RATE = 16000;
// The speech server emits 24 kHz PCM. The playback AudioContext must run at
// the same rate: at any other rate the browser resamples every chunk on its
// own, with no filter history carried across chunks, so each boundary gets a
// transient — an audible tick roughly three times a second.
const PLAYBACK_SAMPLE_RATE = 24000;
const FRAME_SAMPLES = 320;
const MAX_PENDING_AUDIO_FRAMES = 250;

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

type ChatEntry =
  | {
      kind: "message";
      id: number;
      role: "user" | "assistant";
      text: string;
      tools?: string[];
      webSources?: string[];
      materialSources?: VoiceMaterialSource[];
      timing?: string;
      symbolState: CourseAgentSymbolState;
    }
  | { kind: "visualization"; id: number; visualization: VoiceVisualization };

const GREETING =
  "안녕하세요. COURSE AGENT입니다. 강의 내용 중 막힌 부분을 텍스트나 음성으로 질문해 주세요.";

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
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [isMuted, setIsMuted] = useState(false);
  const [isVoiceOpen, setIsVoiceOpen] = useState(false);
  const [isMicrophoneAvailable, setIsMicrophoneAvailable] = useState(true);
  const [weakConcepts, setWeakConcepts] = useState<WeakConcept[]>([]);
  const [weakConceptError, setWeakConceptError] = useState<string | null>(null);
  const [isWeakConceptLoading, setIsWeakConceptLoading] = useState(true);

  const nextId = useRef(1);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const micUnavailableRef = useRef(false);
  const captureContextRef = useRef<AudioContext | null>(null);
  const playContextRef = useRef<AudioContext | null>(null);
  const rateMismatchLoggedRef = useRef(false);
  const pcmBufferRef = useRef<Float32Array>(new Float32Array(0));
  const pendingAudioFramesRef = useRef<string[]>([]);
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

  useEffect(() => {
    const node = messagesRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [entries]);

  // Reopening a stored conversation replays it, then keeps answering in it.
  useEffect(() => {
    if (!initialSessionId) return;
    let isCancelled = false;

    getChatSession(initialSessionId)
      .then((detail) => {
        if (isCancelled) return;
        const replayed: ChatEntry[] = detail.logs.flatMap((log) => [
          {
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

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || isSending) return;

    appendMessage({ role: "user", text, symbolState: "presence" });
    const pendingId = appendMessage({
      role: "assistant",
      text: "답변을 준비하고 있습니다.",
      symbolState: "flow"
    });
    setQuestion("");
    setIsSending(true);

    const liveSocket = socketRef.current;
    if (isVoiceOpen && liveSocket?.readyState === WebSocket.OPEN) {
      lastLocalTextRef.current = text.toLocaleLowerCase().trim().replace(/\s+/g, " ");
      voiceTurnRef.current = {
        pendingId,
        streamStarted: false,
        tools: []
      };
      setVoiceState("thinking");
      liveSocket.send(JSON.stringify({ type: "text", text }));
      return;
    }

    let streamed = "";
    try {
      const answer: VoiceAnswer = await streamVoiceAnswer(
        courseId,
        { chat_session_id: chatSessionId, mode: "socratic", text },
        (token) => {
          streamed += token;
          patchMessage(pendingId, { text: streamed, symbolState: "flow" });
        },
        (message) => {
          if (!streamed) {
            patchMessage(pendingId, { text: message, symbolState: "flow" });
          }
        }
      );
      setChatSessionId(answer.session_id);
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
      patchMessage(pendingId, {
        symbolState: "error",
        text: `오류: ${error instanceof Error ? error.message : "답변을 생성하지 못했습니다."}`
      });
    } finally {
      setIsSending(false);
    }
  };

  const handleNewChat = async () => {
    if (isVoiceOpen) stopVoice();
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
  }, []);

  const playChunk = useCallback((bytes: Uint8Array, rate: number) => {
    const context = playContextRef.current;
    if (!context || bytes.byteLength < 2) return;
    const usable = bytes.byteLength - (bytes.byteLength % 2);
    const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, usable / 2);
    if (rate !== context.sampleRate && !rateMismatchLoggedRef.current) {
      rateMismatchLoggedRef.current = true;
      console.warn(
        `[voice] playback context is ${context.sampleRate} Hz but audio is ${rate} Hz; ` +
          "each chunk will be resampled separately and boundaries may tick"
      );
    }
    const buffer = context.createBuffer(1, pcm.length, rate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;

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
          if (turn.pendingId === undefined) {
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
        appendMessage({
          role: "assistant",
          symbolState: "error",
          text: `오류: ${String(message.message ?? "")}`
        });
        setVoiceState("listening");
        setIsSending(false);
      }
    },
    [appendMessage, appendVisualizations, flushPlayback, patchMessage, playChunk]
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
    voiceTurnRef.current = { tools: [] };
    voiceTranscriptMessageIdsRef.current.clear();
    setIsVoiceOpen(false);
    setIsMicrophoneAvailable(true);
    setIsMuted(false);
    setIsSending(false);
    setVoiceState("idle");
  }, [flushPlayback]);

  useEffect(() => stopVoice, [stopVoice]);

  const startVoice = async () => {
    micUnavailableRef.current = false;
    setIsMicrophoneAvailable(true);
    setIsVoiceOpen(true);
    setVoiceState("connecting");

    try {
      const playContext = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE });
      void playContext.resume().catch(() => undefined);
      playContextRef.current = playContext;
      nextPlayAtRef.current = 0;

      const socket = new WebSocket(voiceStreamUrl(courseId, chatSessionId));
      socket.onopen = () => {
        pendingAudioFramesRef.current.forEach((payload) => socket.send(payload));
        pendingAudioFramesRef.current = [];
      };
      socket.onmessage = handleSocketMessage;
      socket.onclose = () => {
        socketRef.current = null;
        setIsVoiceOpen(false);
        setVoiceState("idle");
      };
      socketRef.current = socket;
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
          <div aria-live="polite" className="voice-messages" ref={messagesRef}>
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
                    <div className="voice-bubble">{entry.text}</div>
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
          <form className="voice-chat-form" onSubmit={handleSubmit}>
            <input
              aria-label="AI 조교에게 질문"
              autoComplete="off"
              disabled={isSending}
              maxLength={4000}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="예: 강의자료에서 정상성과 차분의 관계를 찾아 설명해줘"
              value={question}
            />
            <button className="voice-primary" disabled={isSending} type="submit">
              전송
            </button>
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
