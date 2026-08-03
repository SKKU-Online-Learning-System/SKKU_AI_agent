// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatLogListResponse } from "../../lib/api";
import { ChatLogClient } from "./chat-log-client";

const apiMocks = vi.hoisted(() => ({
  getAdminChatLog: vi.fn(),
  getCourseChatLog: vi.fn(),
  listAdminChatLogs: vi.fn(),
  listCourseChatLogs: vi.fn(),
  listCourses: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    getAdminChatLog: apiMocks.getAdminChatLog,
    getCourseChatLog: apiMocks.getCourseChatLog,
    listAdminChatLogs: apiMocks.listAdminChatLogs,
    listCourseChatLogs: apiMocks.listCourseChatLogs,
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

const logResponse: ChatLogListResponse = {
  logs: [
    {
      id: "log-1",
      courseId: "course-1",
      courseName: "인공지능개론",
      userLabel: "ch***@skku.edu",
      userId: null,
      question: "경사하강법이 뭐야?",
      answerPreview: "경사하강법은 손실 함수를...",
      isGrounded: true,
      answerSourceType: "rag",
      safetyCategory: "normal",
      createdAt: "2026-08-01T00:00:00Z"
    }
  ],
  total: 1
};

beforeEach(() => {
  apiMocks.listCourses.mockResolvedValue([course]);
  apiMocks.listCourseChatLogs.mockResolvedValue(logResponse);
  apiMocks.listAdminChatLogs.mockResolvedValue(logResponse);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("ChatLogClient", () => {
  it("loads the professor's own course logs with a masked user label", async () => {
    render(<ChatLogClient audience="professor" />);

    expect(await screen.findByText("경사하강법이 뭐야?")).toBeInTheDocument();
    expect(screen.getByText("ch***@skku.edu")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "강의자료 기반" })).toBeInTheDocument();
    expect(apiMocks.listCourseChatLogs).toHaveBeenCalledWith("course-1", {
      keyword: undefined,
      isGrounded: null
    });
  });

  it("offers an all-courses option for admins", async () => {
    render(<ChatLogClient audience="admin" />);

    expect(await screen.findByText("경사하강법이 뭐야?")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "전체 과목" })).toBeInTheDocument();
    expect(apiMocks.listAdminChatLogs).toHaveBeenCalled();
  });

  it("applies the keyword and grounded filters on submit", async () => {
    render(<ChatLogClient audience="professor" />);
    await screen.findByText("경사하강법이 뭐야?");

    fireEvent.change(screen.getByLabelText("검색어"), { target: { value: "경사" } });
    fireEvent.change(screen.getByLabelText("자료 기반 여부"), { target: { value: "false" } });
    fireEvent.click(screen.getByRole("button", { name: "검색" }));

    expect(apiMocks.listCourseChatLogs).toHaveBeenLastCalledWith("course-1", {
      keyword: "경사",
      isGrounded: false
    });
  });

  it("opens the log detail with sources and safety result", async () => {
    apiMocks.getCourseChatLog.mockResolvedValue({
      id: "log-1",
      courseId: "course-1",
      courseName: "인공지능개론",
      userLabel: "ch***@skku.edu",
      userId: null,
      question: "경사하강법이 뭐야?",
      answer: "경사하강법은 손실 함수를 줄이는 최적화 방법입니다.",
      referencedDocuments: [
        {
          materialId: "material-1",
          documentName: "lecture1.pdf",
          pageNumber: 12,
          chunkIndex: 3,
          score: 0.87
        }
      ],
      retrievalResult: { result_count: 1 },
      safetyResult: { category: "normal", blocked: false },
      isGrounded: true,
      answerSourceType: "rag",
      modelName: "mock-llm",
      responseTimeMs: 42,
      createdAt: "2026-08-01T00:00:00Z"
    });
    render(<ChatLogClient audience="professor" />);
    fireEvent.click(await screen.findByRole("button", { name: "경사하강법이 뭐야?" }));

    expect(await screen.findByText("로그 상세")).toBeInTheDocument();
    expect(screen.getByText("lecture1.pdf (p.12)")).toBeInTheDocument();
    expect(screen.getByText("mock-llm")).toBeInTheDocument();
  });

  it("shows an empty state when there is nothing to review", async () => {
    apiMocks.listCourseChatLogs.mockResolvedValue({ logs: [], total: 0 });

    render(<ChatLogClient audience="professor" />);

    expect(await screen.findByText("조회된 질문 로그가 없습니다.")).toBeInTheDocument();
  });
});
