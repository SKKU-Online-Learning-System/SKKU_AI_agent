// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RagDebugClient } from "./rag-debug-client";

const mocks = vi.hoisted(() => ({
  listCourses: vi.fn(),
  searchRagDebug: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    listCourses: mocks.listCourses,
    searchRagDebug: mocks.searchRagDebug
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RagDebugClient", () => {
  it("searches the selected course once and displays diagnostics and sources", async () => {
    mocks.listCourses.mockResolvedValue([
      {
        id: "course-1",
        code: "AI101",
        title: "인공지능개론",
        term: "2026-2",
        instructorId: "professor-1",
        instructorName: "교수자",
        agentStatus: "active",
        createdAt: "2026-07-20T00:00:00Z",
        updatedAt: "2026-07-20T00:00:00Z"
      }
    ]);
    let resolveSearch!: (value: unknown) => void;
    mocks.searchRagDebug.mockReturnValue(
      new Promise((resolve) => {
        resolveSearch = resolve;
      })
    );
    render(<RagDebugClient />);

    expect(await screen.findByRole("option", { name: "인공지능개론 (2026-2)" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("질문"), {
      target: { value: "경사하강법이 뭐야?" }
    });
    fireEvent.change(screen.getByLabelText("top_k"), { target: { value: "3" } });
    const form = screen.getByRole("button", { name: "검색 실행" }).closest("form");
    fireEvent.submit(form!);
    fireEvent.submit(form!);

    expect(mocks.searchRagDebug).toHaveBeenCalledTimes(1);
    expect(mocks.searchRagDebug).toHaveBeenCalledWith(
      "course-1",
      "경사하강법이 뭐야?",
      3
    );
    expect(screen.getByRole("button", { name: "검색 중..." })).toBeDisabled();

    resolveSearch({
      courseId: "course-1",
      question: "경사하강법이 뭐야?",
      topK: 3,
      debug: {
        embeddingModel: "local-hash",
        searchMode: "local_cosine",
        totalCandidateChunks: 7
      },
      results: [
        {
          chunkId: "chunk-1",
          materialId: "material-1",
          documentName: "ai-intro.txt",
          pageNumber: null,
          chunkIndex: 2,
          chunkText: "경사하강법은 손실 함수를 줄이는 최적화 방법이다.",
          score: 0.87654
        }
      ]
    });

    expect(await screen.findByText("score 0.8765")).toBeInTheDocument();
    expect(screen.getByText("ai-intro.txt")).toBeInTheDocument();
    expect(screen.getByText("material-1")).toBeInTheDocument();
    expect(screen.getByText("chunk-1")).toBeInTheDocument();
    expect(screen.getByText("local-hash")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "검색 실행" })).toBeEnabled());
  });
});
