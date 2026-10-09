// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getChatSession } from "../../lib/api";
import type { VoiceAnswer, VoiceStreamHandlers } from "../../lib/voice-api";
import {
  deleteVoiceAttachment,
  getVoiceAttachment,
  listWeakConcepts,
  streamVoiceAnswer,
  uploadVoiceAttachment,
  voiceStreamUrl
} from "../../lib/voice-api";
import { CourseAgentClient, transcriptFollowKey } from "./course-agent-client";
import type { ChatEntry } from "./course-agent-client";
import { EMPTY_TRACE } from "./course-agent-trace";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, getChatSession: vi.fn() };
});

vi.mock("../../lib/voice-api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/voice-api")>(
    "../../lib/voice-api"
  );
  return {
    ...actual,
    getVoiceConfig: vi.fn().mockResolvedValue({
      can_manage: false,
      course_id: "course-1",
      course_name: "테스트 강의",
      is_search_ready: true,
      material_count: 1,
      term: "2026-2",
      trusted_sites: [],
      voice_enabled: true,
      voice_provider: "local_cascade",
      voice_status: { detail: "ok", enabled: true, provider: "local_cascade", services: {} }
    }),
    listWeakConcepts: vi.fn().mockResolvedValue({ concepts: [] }),
    streamVoiceAnswer: vi.fn(),
    uploadVoiceAttachment: vi.fn(),
    getVoiceAttachment: vi.fn(),
    deleteVoiceAttachment: vi.fn().mockResolvedValue(undefined),
    voiceStreamUrl: vi.fn().mockReturnValue("ws://localhost/voice")
  };
});

const ANSWER: VoiceAnswer = {
  attachments: [],
  log_id: "log-1",
  material_sources: [],
  reply: "경사하강법은 기울기를 따라 내려가요. 왜 반대 방향일까요?",
  safety: { blocked: false, category: "normal" },
  session_id: "session-1",
  sources: [],
  timings: { total: 1234 },
  tools: [],
  transcript: "경사하강법이 뭐야?",
  visualizations: []
};

async function ask(text: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "AI 조교에게 질문" }), {
    target: { value: text }
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "전송" }));
  });
}

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.OPEN;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onopen: (() => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  close() {}
  send(payload: string) {
    this.sent.push(payload);
  }

  /** Simulate the server or the network dropping the connection. */
  drop() {
    this.readyState = 3;
    this.onclose?.();
  }
}

class MockAudioContext {
  static stopped = 0;

  currentTime = 0;
  destination = {};
  sampleRate = 48000;

  createBuffer(_channels: number, length: number, rate: number) {
    return { duration: length / rate, getChannelData: () => new Float32Array(length) };
  }
  createBufferSource() {
    return {
      buffer: null as unknown,
      connect() {},
      onended: null as (() => void) | null,
      start() {},
      stop() {
        MockAudioContext.stopped += 1;
      }
    };
  }
  close() {
    return Promise.resolve();
  }
  resume() {
    return Promise.resolve();
  }
}

describe("CourseAgentClient microphone fallback", () => {
  beforeEach(() => {
    vi.mocked(listWeakConcepts).mockResolvedValue({ concepts: [] });
    MockWebSocket.instances = [];
    MockAudioContext.stopped = 0;
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("AudioContext", MockAudioContext);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException("없음", "NotFoundError")) }
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("replaces the progress notice with the answer instead of stacking a line", async () => {
    render(<CourseAgentClient courseId="course-1" />);
    const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

    const socket = MockWebSocket.instances[0];
    const deliver = (payload: Record<string, unknown>) =>
      act(() => {
        socket.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
      });

    deliver({ text: "질문을 살펴보고 있어요. 잠시만 기다려 주세요.", transient: true, type: "filler" });
    expect(screen.getByText(/질문을 살펴보고 있어요/)).toBeInTheDocument();

    deliver({ text: "주소 공간을 넓혀 줍니다.", type: "token" });
    deliver({
      item_id: "local-1-agent",
      text: "주소 공간을 넓혀 줍니다.",
      type: "transcript",
      who: "agent"
    });

    // One assistant bubble for the turn: the notice is progress, not a turn.
    expect(screen.getByText("주소 공간을 넓혀 줍니다.")).toBeInTheDocument();
    expect(screen.queryByText(/질문을 살펴보고 있어요/)).not.toBeInTheDocument();
  });

  it.each([
    ["barge-in", { type: "flush" }],
    ["a failed turn", { message: "답변을 만들지 못했어요.", type: "error" }]
  ])("discards the notice bubble on %s so the next answer keeps its place", async (_label, kill) => {
    render(<CourseAgentClient courseId="course-1" />);
    const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

    const socket = MockWebSocket.instances[0];
    const deliver = (payload: Record<string, unknown>) =>
      act(() => {
        socket.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
      });

    deliver({
      item_id: "local-1-user",
      text: "첫 질문이에요",
      type: "transcript",
      who: "user"
    });
    deliver({ text: "질문을 살펴보고 있어요. 잠시만 기다려 주세요.", transient: true, type: "filler" });
    expect(screen.getByText(/질문을 살펴보고 있어요/)).toBeInTheDocument();

    // The turn dies before any answer exists, so its bubble has nothing to show.
    deliver(kill);
    expect(screen.queryByText(/질문을 살펴보고 있어요/)).not.toBeInTheDocument();

    // The next turn must own its own bubble, below its own question.
    deliver({
      item_id: "local-2-user",
      text: "두 번째 질문이에요",
      type: "transcript",
      who: "user"
    });
    deliver({ text: "두 번째 답이에요.", type: "token" });

    const rendered = screen.getAllByText(/질문이에요|두 번째 답이에요\./).map((n) => n.textContent);
    expect(rendered).toEqual(["첫 질문이에요", "두 번째 질문이에요", "두 번째 답이에요."]);
  });

  it("stops the agent mid-answer when the student submits a typed turn", async () => {
    // Submitting interrupts, exactly as speaking over the agent does. Only a
    // spoken barge-in gets a server flush, and typing is the whole way a student
    // with no microphone interrupts.
    render(<CourseAgentClient courseId="course-1" />);
    const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

    act(() => {
      MockWebSocket.instances[0].onmessage?.({
        data: JSON.stringify({ data: "AAAAAAAA", rate: 24000, type: "audio" })
      } as MessageEvent<string>);
    });
    expect(MockAudioContext.stopped).toBe(0);

    fireEvent.change(screen.getByRole("textbox", { name: "AI 조교에게 질문" }), {
      target: { value: "그만하고 이거 알려줘" }
    });
    fireEvent.click(screen.getByRole("button", { name: "전송" }));

    expect(MockAudioContext.stopped).toBeGreaterThan(0);
    expect(MockWebSocket.instances[0].sent).toEqual([
      JSON.stringify({ type: "text", text: "그만하고 이거 알려줘" })
    ]);
  });

  it("ends a turn the dropped socket took with it instead of stranding its bubble", async () => {
    // The server cancels the in-flight turn when the connection closes and
    // nothing replays it, so the notice bubble would otherwise sit on
    // "질문을 살펴보고 있어요..." forever -- and then swallow the next turn's
    // answer, because the stale pendingId is what the next patch targets.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<CourseAgentClient courseId="course-1" />);
      const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
      await waitFor(() => expect(start).toBeEnabled());
      fireEvent.click(start);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

      const deliver = (socket: MockWebSocket, payload: Record<string, unknown>) =>
        act(() => {
          socket.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
        });

      deliver(MockWebSocket.instances[0], {
        item_id: "local-1-user",
        text: "가상 메모리가 뭐야?",
        type: "transcript",
        who: "user"
      });
      deliver(MockWebSocket.instances[0], {
        text: "질문을 살펴보고 있어요. 잠시만 기다려 주세요.",
        transient: true,
        type: "filler"
      });
      expect(screen.getByText(/질문을 살펴보고 있어요/)).toBeInTheDocument();

      // Drops mid-think — exactly the window the notice exists to cover.
      act(() => MockWebSocket.instances[0].drop());
      expect(screen.queryByText(/질문을 살펴보고 있어요/)).not.toBeInTheDocument();
      expect(screen.getByText(/답변이 중단됐어요/)).toBeInTheDocument();

      await vi.advanceTimersByTimeAsync(1000);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));

      deliver(MockWebSocket.instances[1], {
        item_id: "local-2-user",
        text: "다시 질문할게요",
        type: "transcript",
        who: "user"
      });
      deliver(MockWebSocket.instances[1], { text: "새 답변이에요.", type: "token" });

      // The next answer is its own bubble; the abandoned one stays abandoned.
      expect(screen.getByText(/답변이 중단됐어요/)).toBeInTheDocument();
      expect(screen.getByText("새 답변이에요.")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a typed turn on the voice path across a reconnect", async () => {
    // Typing with the panel open means the student cannot use the microphone,
    // not that they want the typed-only chatbot. The turn has to reach the voice
    // agent and come back as speech, so a reconnect gap must not reroute it.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<CourseAgentClient courseId="course-1" />);
      const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
      await waitFor(() => expect(start).toBeEnabled());
      fireEvent.click(start);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

      MockWebSocket.instances[0].drop();
      fireEvent.change(screen.getByRole("textbox", { name: "AI 조교에게 질문" }), {
        target: { value: "연결이 끊긴 사이의 질문" }
      });
      fireEvent.click(screen.getByRole("button", { name: "전송" }));

      // Nothing is sent through the typed-only path while the panel is open.
      expect(streamVoiceAnswer).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(1000);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
      MockWebSocket.instances[1].onopen?.();

      expect(MockWebSocket.instances[1].sent).toEqual([
        JSON.stringify({ type: "text", text: "연결이 끊긴 사이의 질문" })
      ]);
      expect(streamVoiceAnswer).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps realtime open and sends typed turns when no microphone exists", async () => {
    render(<CourseAgentClient courseId="course-1" />);

    const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    expect(
      await screen.findByText("마이크 없음 · 채팅창에 입력해 대화하세요")
    ).toBeInTheDocument();
    expect(MockWebSocket.instances).toHaveLength(1);

    fireEvent.change(screen.getByRole("textbox", { name: "AI 조교에게 질문" }), {
      target: { value: "마이크 없이 질문" }
    });
    fireEvent.click(screen.getByRole("button", { name: "전송" }));

    expect(MockWebSocket.instances[0].sent).toEqual([
      JSON.stringify({ type: "text", text: "마이크 없이 질문" })
    ]);
  });

  it("retries a dropped realtime connection and finally says so", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<CourseAgentClient courseId="course-1" />);

      const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
      await waitFor(() => expect(start).toBeEnabled());
      fireEvent.click(start);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

      // Two quiet retries cover a blip or a backend restart.
      MockWebSocket.instances[0].drop();
      await vi.advanceTimersByTimeAsync(1000);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
      MockWebSocket.instances[1].drop();
      await vi.advanceTimersByTimeAsync(3000);
      await waitFor(() => expect(MockWebSocket.instances).toHaveLength(3));

      // The third drop is not retried: the panel used to close with no word at all.
      MockWebSocket.instances[2].drop();
      expect(
        await screen.findByText(/음성 연결이 끊어졌어요/)
      ).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(5000);
      expect(MockWebSocket.instances).toHaveLength(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows this course's saved weak concepts and mastery", async () => {
    vi.mocked(listWeakConcepts).mockResolvedValue({
      concepts: [
        {
          concept: "경사하강법의 학습률",
          difficulty_note: "학습률이 너무 클 때 발산하는 이유를 혼동함",
          failure_count: 2,
          last_seen_at: 1_777_000_000,
          mastery_percent: 67,
          memory_id: "memory-1",
          next_review_at: 1_777_086_400,
          status: "practicing",
          success_count: 2
        }
      ]
    });

    render(<CourseAgentClient courseId="course-1" />);

    expect(await screen.findByText("경사하강법의 학습률")).toBeInTheDocument();
    expect(screen.getByText("학습률이 너무 클 때 발산하는 이유를 혼동함")).toBeInTheDocument();
    expect(screen.getByText("학습 중")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "경사하강법의 학습률 이해도" })).toHaveAttribute(
      "aria-valuenow",
      "67"
    );
    expect(screen.getByText("67%")).toBeInTheDocument();
  });

  it("offers only Socratic teaching and resumes the visible session in voice", async () => {
    vi.mocked(getChatSession).mockResolvedValue({ logs: [] } as unknown as Awaited<
      ReturnType<typeof getChatSession>
    >);
    render(<CourseAgentClient courseId="course-1" initialSessionId="saved-session" />);
    const start = await screen.findByRole("button", { name: "음성으로 질문하기" });
    await waitFor(() => expect(start).toBeEnabled());
    expect(screen.queryByText("설명 모드")).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "챗봇 답변 모드" })).not.toBeInTheDocument();
    fireEvent.click(start);
    await waitFor(() => expect(voiceStreamUrl).toHaveBeenCalledWith("course-1", "saved-session"));
  });
});

describe("CourseAgentClient typed turns", () => {
  beforeEach(() => {
    vi.mocked(listWeakConcepts).mockResolvedValue({ concepts: [] });
    vi.mocked(streamVoiceAnswer).mockReset();
    vi.mocked(uploadVoiceAttachment).mockReset();
    vi.mocked(getVoiceAttachment).mockReset();
    vi.mocked(deleteVoiceAttachment).mockReset().mockResolvedValue(undefined);
    MockWebSocket.instances = [];
    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("AudioContext", MockAudioContext);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows a folded 생각 중… line that opens onto the steps and reasoning, then says how long it took", async () => {
    let finish: (() => void) | undefined;
    vi.mocked(streamVoiceAnswer).mockImplementation(async (_course, _payload, handlers) => {
      const h = handlers as VoiceStreamHandlers;
      h.onStatus?.("경사하강법이요? 네, 잠깐 정리해 볼게요.");
      h.onStep?.({
        detail: "경사하강법이 뭐야?",
        key: "material",
        label: "강의자료를 검색하는 중",
        stage: "material",
        state: "running"
      });
      h.onStep?.({
        detail: "lecture1.pdf p.3",
        elapsed_ms: 412,
        key: "material",
        label: "강의자료 1곳을 찾았어요",
        stage: "material",
        state: "done"
      });
      h.onStep?.({ key: "llm-1", label: "답을 구성하는 중", stage: "llm", state: "running" });
      h.onThinking?.("The student asks for the definition. ", "llm-1");
      h.onThought?.("학생이 정의를 묻는 것으로 읽는다", "llm-1");
      h.onThinking?.("Check the evidence first.", "llm-1");
      h.onThought?.("근거를 먼저 확인한다", "llm-1");
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      h.onStep?.({ detail: "생각 1.4초 · 작성 0.7초", elapsed_ms: 2100, key: "llm-1",
        label: "답변을 정리했어요", stage: "llm", state: "done" });
      h.onToken("경사하강법은 ");
      return ANSWER;
    });

    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });
    await ask("경사하강법이 뭐야?");

    // While the turn runs the quiet line shows, trailed by the newest headline
    // of what the model is doing; the notice sits in the bubble.
    const toggle = await screen.findByRole("button", { name: "생각 중…" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("강의자료 1곳을 찾았어요")).not.toBeInTheDocument();
    expect(screen.getByText("근거를 먼저 확인한다")).toHaveClass("voice-trace-now");
    expect(screen.getByText(/잠깐 정리해 볼게요/)).toBeInTheDocument();

    // Opening it shows the step updated in place, the headlines as their own
    // lines under the round they belong to (newest still forming), and the raw
    // reasoning folded away beneath them.
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("강의자료 1곳을 찾았어요")).toBeInTheDocument();
    expect(screen.queryByText("강의자료를 검색하는 중")).not.toBeInTheDocument();
    expect(screen.getByText("lecture1.pdf p.3")).toBeInTheDocument();
    expect(screen.getByText("답을 구성하는 중")).toBeInTheDocument();
    const thoughts = screen.getAllByRole("listitem").filter((item) =>
      item.classList.contains("voice-trace-thought")
    );
    expect(thoughts.map((item) => item.textContent)).toEqual([
      "학생이 정의를 묻는 것으로 읽는다",
      "근거를 먼저 확인한다"
    ]);
    expect(thoughts[1]).toHaveAttribute("data-current", "true");
    expect(thoughts[0]).not.toHaveAttribute("data-current");
    expect(screen.queryByText("근거를 먼저 확인한다", { selector: ".voice-trace-now" })).toBeNull();
    const raw = screen.getByText("생각 원문 보기").closest("details");
    expect(raw).not.toHaveAttribute("open");
    expect(raw).toHaveTextContent("The student asks for the definition. Check the evidence first.");

    await act(async () => {
      finish?.();
    });

    // Answered: the line says how long it took and, opened by the student, stays open.
    expect(await screen.findByText(ANSWER.reply)).toBeInTheDocument();
    const finished = screen.getByRole("button", { name: /초 동안 생각함$/ });
    expect(finished).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("답변을 정리했어요")).toBeInTheDocument();
    expect(screen.getByText("생각 1.4초 · 작성 0.7초")).toBeInTheDocument();
    expect(screen.getByText("2.1초")).toBeInTheDocument();
    // Settled: no headline is "current" any more, and no reasoning leaked into the reply.
    expect(document.querySelector('.voice-trace-thought[data-current="true"]')).toBeNull();
    expect(screen.getByText(ANSWER.reply).textContent).not.toContain("Check the evidence");
    fireEvent.click(finished);
    expect(screen.queryByText("답변을 정리했어요")).not.toBeInTheDocument();
  });

  it("replaces a discarded draft instead of appending the regenerated one", async () => {
    vi.mocked(streamVoiceAnswer).mockImplementation(async (_course, _payload, handlers) => {
      const h = handlers as VoiceStreamHandlers;
      h.onToken("첫 초안은 여기까지");
      h.onRewind?.();
      h.onStep?.({ key: "llm-1", label: "생각이 길어져 답부터 씁니다", stage: "llm",
        state: "running" });
      h.onToken("경사하강법은 ");
      h.onToken("기울기를 따라 내려가요. 왜 반대 방향일까요?");
      return ANSWER;
    });

    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });
    await ask("경사하강법이 뭐야?");

    expect(await screen.findByText(ANSWER.reply)).toBeInTheDocument();
    expect(screen.queryByText(/첫 초안은 여기까지/)).not.toBeInTheDocument();
  });

  it("keeps the trace folded when the student never opened it", async () => {
    vi.mocked(streamVoiceAnswer).mockImplementation(async (_course, _payload, handlers) => {
      const h = handlers as VoiceStreamHandlers;
      h.onStep?.({ key: "llm-1", label: "답을 구성하는 중", stage: "llm", state: "running" });
      h.onThought?.("정의부터 확인한다", "llm-1");
      h.onToken("경사하강법은 ");
      h.onStep?.({ key: "llm-1", label: "답변을 정리했어요", stage: "llm", state: "done" });
      return ANSWER;
    });

    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });
    await ask("경사하강법이 뭐야?");

    expect(await screen.findByText(ANSWER.reply)).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /초 동안 생각함$/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("정의부터 확인한다")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.getByText("정의부터 확인한다")).toBeInTheDocument();
    expect(screen.getByText("답변을 정리했어요")).toBeInTheDocument();
  });

  it("marks whatever was still running as failed when the turn errors", async () => {
    vi.mocked(streamVoiceAnswer).mockImplementation(async (_course, _payload, handlers) => {
      const h = handlers as VoiceStreamHandlers;
      h.onStep?.({ key: "material", label: "강의자료 1곳을 찾았어요", stage: "material",
        state: "done" });
      h.onStep?.({ key: "llm-1", label: "답을 구성하는 중", stage: "llm", state: "running" });
      throw new Error("답변 생성 서비스를 사용할 수 없습니다.");
    });

    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });
    await ask("경사하강법이 뭐야?");

    expect(await screen.findByText(/오류: 답변 생성 서비스를 사용할 수 없습니다/)).toBeInTheDocument();
    // The line says the thinking stopped, and nothing is left spinning under it.
    const toggle = screen.getByRole("button", { name: "생각이 중단됨" });
    fireEvent.click(toggle);
    const steps = screen.getAllByRole("listitem").filter((item) =>
      item.classList.contains("voice-trace-step")
    );
    expect(steps.map((item) => item.getAttribute("data-state"))).toEqual(["done", "failed"]);
    // The composer is usable again.
    expect(screen.getByRole("button", { name: "전송" })).toBeEnabled();
  });

  it("shows no empty bubble before the notice or the first token arrives", async () => {
    let finish: (() => void) | undefined;
    vi.mocked(streamVoiceAnswer).mockImplementation(async (_course, _payload, handlers) => {
      const h = handlers as VoiceStreamHandlers;
      h.onStep?.({ key: "llm-1", label: "답을 구성하는 중", stage: "llm", state: "running" });
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
      h.onToken(ANSWER.reply);
      return ANSWER;
    });

    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });
    await ask("경사하강법이 뭐야?");

    await screen.findByRole("button", { name: "생각 중…" });
    const bubbles = document.querySelectorAll('.voice-message[data-role="assistant"] .voice-bubble');
    // Only the greeting has a bubble; the pending turn is just its 생각 중… line.
    expect(bubbles).toHaveLength(1);
    expect(screen.queryByText("답변을 준비하고 있습니다.")).not.toBeInTheDocument();

    await act(async () => {
      finish?.();
    });
    expect(await screen.findByText(ANSWER.reply)).toBeInTheDocument();
  });

  it("uploads an attached file, sends its id with the question and shows it on the message", async () => {
    vi.mocked(uploadVoiceAttachment).mockResolvedValue({
      chars: 0,
      id: "att-1",
      kind: "pdf",
      name: "notes.pdf",
      pages: 3,
      size: 2048
    });
    vi.mocked(streamVoiceAnswer).mockResolvedValue({
      ...ANSWER,
      attachments: [{ chars: 900, id: "att-1", kind: "pdf", name: "notes.pdf", pages: 3, size: 2048 }]
    });

    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });

    const file = new File(["%PDF-1.4"], "notes.pdf", { type: "application/pdf" });
    await act(async () => {
      fireEvent.change(screen.getByLabelText("첨부할 파일 선택"), { target: { files: [file] } });
    });
    expect(uploadVoiceAttachment).toHaveBeenCalledWith("course-1", file);
    expect(await screen.findByText("PDF · 3쪽")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "notes.pdf 첨부 취소" })).toBeInTheDocument();

    await ask("이 자료 핵심만 짚어줘");

    expect(streamVoiceAnswer).toHaveBeenCalledWith(
      "course-1",
      expect.objectContaining({ attachment_ids: ["att-1"], text: "이 자료 핵심만 짚어줘" }),
      expect.anything()
    );
    // The composer is empty again and the file now sits on the sent question.
    expect(screen.queryByRole("button", { name: "notes.pdf 첨부 취소" })).not.toBeInTheDocument();
    const sent = screen.getByRole("list", { name: "첨부 파일" });
    expect(sent).toHaveTextContent("notes.pdf");
    expect(sent).toHaveTextContent("PDF · 3쪽");
    expect(await screen.findByText(ANSWER.reply)).toBeInTheDocument();
  });

  it("indexes a long PDF, waits for it, then keeps it pinned across questions", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const book = {
        chars: 0, id: "book-1", index: { pages: 312, pages_done: 0, status: "indexing" as const },
        kind: "pdf" as const, mode: "excerpt" as const, name: "교재.pdf", pages: 312, size: 5_000_000
      };
      vi.mocked(uploadVoiceAttachment).mockResolvedValue(book);
      vi.mocked(getVoiceAttachment)
        .mockResolvedValueOnce({ ...book, index: { pages: 312, pages_done: 120, status: "indexing" } })
        .mockResolvedValue({ ...book, index: { pages: 312, pages_done: 312, status: "ready" } });
      vi.mocked(streamVoiceAnswer).mockResolvedValue({
        ...ANSWER,
        attachments: [{ ...book, chars: 900, index: null, pages_used: [12, 13] }]
      });

      render(<CourseAgentClient courseId="course-1" />);
      await screen.findByRole("button", { name: "음성으로 질문하기" });
      await act(async () => {
        fireEvent.change(screen.getByLabelText("첨부할 파일 선택"), {
          target: { files: [new File(["%PDF-1.4"], "교재.pdf", { type: "application/pdf" })] }
        });
      });

      // Sending waits for the index, and the chip says how far it is.
      expect(await screen.findByText("색인 중 0/312쪽")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "전송" })).toBeDisabled();
      await vi.advanceTimersByTimeAsync(1600);
      expect(await screen.findByText("색인 중 120/312쪽")).toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(1600);
      expect(await screen.findByText("PDF · 312쪽 · 질문마다 관련 쪽 참고")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "전송" })).toBeEnabled();

      await ask("소프트맥스가 뭐야?");
      expect(streamVoiceAnswer).toHaveBeenLastCalledWith(
        "course-1",
        expect.objectContaining({ attachment_ids: ["book-1"] }),
        expect.anything()
      );
      // The sent question shows which pages were used; the book stays in the composer.
      expect(await screen.findByText("PDF · 12, 13쪽 참고")).toBeInTheDocument();
      expect(screen.getByText(/대화에 유지 · PDF · 312쪽/)).toBeInTheDocument();
      expect(screen.getByText(/긴 PDF는 대화에 남아/)).toBeInTheDocument();

      await ask("경사하강법은?");
      expect(streamVoiceAnswer).toHaveBeenLastCalledWith(
        "course-1",
        expect.objectContaining({ attachment_ids: ["book-1"], text: "경사하강법은?" }),
        expect.anything()
      );

      fireEvent.click(screen.getByRole("button", { name: "교재.pdf 첨부 취소" }));
      expect(deleteVoiceAttachment).toHaveBeenCalledWith("course-1", "book-1");
      expect(screen.queryByText(/대화에 유지/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("refuses files that are not images or PDFs and lets the student remove a file", async () => {
    vi.mocked(uploadVoiceAttachment).mockResolvedValue({
      chars: 0, id: "att-2", kind: "image", name: "photo.png", pages: 1, size: 4096
    });
    render(<CourseAgentClient courseId="course-1" />);
    await screen.findByRole("button", { name: "음성으로 질문하기" });

    await act(async () => {
      fireEvent.change(screen.getByLabelText("첨부할 파일 선택"), {
        target: { files: [new File(["x"], "script.exe", { type: "application/octet-stream" })] }
      });
    });
    expect(uploadVoiceAttachment).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("이미지 또는 PDF만 첨부할 수 있어요.");

    await act(async () => {
      fireEvent.change(screen.getByLabelText("첨부할 파일 선택"), {
        target: { files: [new File(["png"], "photo.png", { type: "image/png" })] }
      });
    });
    expect(await screen.findByText("이미지 · 4KB")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "photo.png 첨부 취소" }));
    expect(screen.queryByText("photo.png")).not.toBeInTheDocument();
    expect(deleteVoiceAttachment).toHaveBeenCalledWith("course-1", "att-2");
  });

  it("does not offer attachments while the voice panel is open", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new DOMException("없음", "NotFoundError")) }
    });
    render(<CourseAgentClient courseId="course-1" />);
    const attach = await screen.findByRole("button", { name: "파일 첨부" });
    expect(attach).toBeEnabled();

    const start = screen.getByRole("button", { name: "음성으로 질문하기" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

    expect(screen.getByRole("button", { name: "파일 첨부" })).toBeDisabled();
    // A typed turn on the voice path carries no trace panel: the answer is spoken.
    fireEvent.change(screen.getByRole("textbox", { name: "AI 조교에게 질문" }), {
      target: { value: "마이크 없이 질문" }
    });
    fireEvent.click(screen.getByRole("button", { name: "전송" }));
    expect(screen.queryByRole("button", { name: /생각/ })).not.toBeInTheDocument();
    expect(streamVoiceAnswer).not.toHaveBeenCalled();
  });
});



describe("transcriptFollowKey", () => {
  const question: ChatEntry = {
    kind: "message",
    id: 1,
    role: "user",
    text: "학습률이 뭐야?",
    symbolState: "presence"
  };
  const pending: ChatEntry = {
    kind: "message",
    id: 2,
    role: "assistant",
    text: "",
    symbolState: "sustain",
    trace: EMPTY_TRACE
  };

  it("does not change when only the agent's trace changes", () => {
    const before = transcriptFollowKey([question, pending]);
    const thinking: ChatEntry = {
      ...pending,
      trace: {
        ...EMPTY_TRACE,
        steps: [{ key: "llm-1", stage: "llm", state: "running", label: "답을 구성하는 중" }],
        thinking: "학습률은 경사하강법의 보폭이고...",
        thoughts: ["이름을 뜯어보며 접근 방식을 정한다"],
        open: true
      }
    };

    expect(transcriptFollowKey([question, thinking])).toBe(before);
  });

  it("changes when a message is added or an answer is written", () => {
    const before = transcriptFollowKey([question, pending]);

    expect(transcriptFollowKey([question])).not.toBe(before);
    expect(transcriptFollowKey([question, { ...pending, text: "경사하강법에서" }])).not.toBe(before);
  });
});
