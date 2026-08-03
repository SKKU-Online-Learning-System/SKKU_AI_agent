// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import type { ChatAnswer, CourseRagStatus } from "../../lib/api";
import { ChatClient } from "./chat-client";

const apiMocks = vi.hoisted(() => ({
  askCourseAgent: vi.fn(),
  getChatSession: vi.fn(),
  getCourseRagStatus: vi.fn(),
  listCourses: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    askCourseAgent: apiMocks.askCourseAgent,
    getChatSession: apiMocks.getChatSession,
    getCourseRagStatus: apiMocks.getCourseRagStatus,
    listCourses: apiMocks.listCourses
  };
});

const course = {
  id: "course-1",
  code: "AI101",
  title: "인공지능개론",
  term: "2026-2",
  instructorId: "professor-1",
  instructorName: "김교수",
  agentStatus: "active" as const,
  createdAt: "2026-08-01T00:00:00Z",
  updatedAt: "2026-08-01T00:00:00Z"
};

const readyStatus: CourseRagStatus = {
  courseId: "course-1",
  materialCount: 1,
  completedMaterialCount: 1,
  failedMaterialCount: 0,
  pendingMaterialCount: 0,
  chunkCount: 8,
  embeddedChunkCount: 8,
  isSearchReady: true
};

const groundedAnswer: ChatAnswer = {
  sessionId: "session-1",
  logId: "log-1",
  answer: "경사하강법은 손실 함수를 줄이는 최적화 방법입니다.",
  sources: [
    {
      materialId: "material-1",
      documentName: "lecture1.pdf",
      pageNumber: 12,
      chunkIndex: 3,
      score: 0.87
    }
  ],
  isGrounded: true,
  answerSourceType: "rag",
  modelName: "mock-llm",
  responseTimeMs: 42,
  retrievalSummary: { resultCount: 1, maxScore: 0.87, scoreThreshold: 0.1, reason: null },
  safety: { blocked: false, category: "normal", reason: null, redirectType: null }
};

beforeEach(() => {
  apiMocks.listCourses.mockResolvedValue([course]);
  apiMocks.getCourseRagStatus.mockResolvedValue(readyStatus);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

async function askQuestion(text: string) {
  await screen.findByText("인공지능개론");
  fireEvent.change(screen.getByLabelText("질문"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "질문 보내기" }));
}

describe("ChatClient", () => {
  it("shows the course header and search readiness", async () => {
    render(<ChatClient courseId="course-1" />);

    expect(await screen.findByText("인공지능개론")).toBeInTheDocument();
    expect(screen.getByText("담당 교수 김교수")).toBeInTheDocument();
    expect(screen.getByText("이 과목은 검색 준비가 완료되었습니다.")).toBeInTheDocument();
  });

  it("warns when no material has been processed", async () => {
    apiMocks.getCourseRagStatus.mockResolvedValue({
      ...readyStatus,
      completedMaterialCount: 0,
      chunkCount: 0,
      embeddedChunkCount: 0,
      isSearchReady: false
    });

    render(<ChatClient courseId="course-1" />);

    expect(
      await screen.findByText("처리된 강의자료가 없어 일반 개념 설명만 제공될 수 있습니다.")
    ).toBeInTheDocument();
  });

  it("renders the answer with its sources and grounded badge", async () => {
    apiMocks.askCourseAgent.mockResolvedValue(groundedAnswer);
    render(<ChatClient courseId="course-1" />);

    await askQuestion("경사하강법이 뭐야?");

    expect(await screen.findByText(groundedAnswer.answer)).toBeInTheDocument();
    expect(screen.getByText("강의자료 기반 답변")).toBeInTheDocument();
    expect(screen.getByText("lecture1.pdf (p.12)")).toBeInTheDocument();
  });

  it("marks an answer without material support as a general explanation", async () => {
    apiMocks.askCourseAgent.mockResolvedValue({
      ...groundedAnswer,
      answer: "일반적인 개념 설명입니다.",
      sources: [],
      isGrounded: false,
      answerSourceType: "general_llm"
    });
    render(<ChatClient courseId="course-1" />);

    await askQuestion("관련 없는 질문");

    expect(await screen.findByText("일반 개념 설명")).toBeInTheDocument();
    expect(screen.queryByText("출처")).not.toBeInTheDocument();
  });

  it("reuses the session id returned by the first answer", async () => {
    apiMocks.askCourseAgent.mockResolvedValue(groundedAnswer);
    render(<ChatClient courseId="course-1" />);

    await askQuestion("경사하강법이 뭐야?");
    await screen.findByText(groundedAnswer.answer);
    fireEvent.change(screen.getByLabelText("질문"), { target: { value: "과적합은?" } });
    fireEvent.click(screen.getByRole("button", { name: "질문 보내기" }));

    await screen.findAllByText(groundedAnswer.answer);
    expect(apiMocks.askCourseAgent).toHaveBeenLastCalledWith({
      courseId: "course-1",
      question: "과적합은?",
      chatSessionId: "session-1"
    });
  });

  it("keeps the send button disabled while a question is empty", async () => {
    render(<ChatClient courseId="course-1" />);
    await screen.findByText("인공지능개론");

    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  });

  it("surfaces an API failure to the user", async () => {
    apiMocks.askCourseAgent.mockRejectedValue(new ApiError(503, "답변 생성에 실패했습니다."));
    render(<ChatClient courseId="course-1" />);

    await askQuestion("경사하강법이 뭐야?");

    expect(await screen.findByRole("alert")).toHaveTextContent("답변 생성에 실패했습니다.");
  });

  it("restores an existing session", async () => {
    apiMocks.getChatSession.mockResolvedValue({
      session: {
        id: "session-1",
        courseId: "course-1",
        courseName: "인공지능개론",
        title: "경사하강법이 뭐야?",
        messageCount: 1,
        lastMessageAt: "2026-08-01T00:00:00Z",
        createdAt: "2026-08-01T00:00:00Z",
        updatedAt: "2026-08-01T00:00:00Z"
      },
      logs: [
        {
          id: "log-1",
          question: "경사하강법이 뭐야?",
          answer: "이전 답변입니다.",
          sources: [],
          isGrounded: true,
          answerSourceType: "rag",
          createdAt: "2026-08-01T00:00:00Z"
        }
      ]
    });

    render(<ChatClient courseId="course-1" initialSessionId="session-1" />);

    expect(await screen.findByText("이전 답변입니다.")).toBeInTheDocument();
    expect(screen.getByText("경사하강법이 뭐야?")).toBeInTheDocument();
  });
});
