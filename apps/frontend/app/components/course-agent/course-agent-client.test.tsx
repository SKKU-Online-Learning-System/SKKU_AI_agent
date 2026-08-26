// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listWeakConcepts } from "../../lib/voice-api";
import { CourseAgentClient } from "./course-agent-client";

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
      voice_enabled: true
    }),
    listWeakConcepts: vi.fn().mockResolvedValue({ concepts: [] }),
    voiceStreamUrl: vi.fn().mockReturnValue("ws://localhost/voice")
  };
});

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.OPEN;
  onclose: (() => void) | null = null;
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
}

class MockAudioContext {
  currentTime = 0;
  sampleRate = 48000;

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

  it("keeps realtime open and sends typed turns when no microphone exists", async () => {
    render(<CourseAgentClient courseId="course-1" />);

    const start = await screen.findByRole("button", { name: "음성 대화 시작" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);

    expect(
      await screen.findByText("마이크 없음 · 채팅창에 입력해 음성 에이전트 테스트")
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
});
