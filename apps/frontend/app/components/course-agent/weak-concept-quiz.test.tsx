// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createWeakConceptQuiz, recordWeakConceptQuiz } from "../../lib/voice-api";
import { WeakConceptQuiz } from "./weak-concept-quiz";

vi.mock("../../lib/voice-api", () => ({
  createWeakConceptQuiz: vi.fn(),
  recordWeakConceptQuiz: vi.fn()
}));

const QUIZ = {
  memory_id: "memory-1",
  concept: "소프트맥스 - 합이 1인 확률",
  topic: "소프트맥스",
  items: [
    {
      statement: "소프트맥스의 출력은 합이 1이다.",
      answer: true,
      explanation: "확률로 바꾸기 때문에 합이 1이에요.",
      source: "3주차.pdf p.12"
    },
    {
      statement: "소프트맥스는 음수 점수를 그대로 남긴다.",
      answer: false,
      explanation: "지수함수를 거치므로 모두 양수가 돼요.",
      source: null
    }
  ]
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WeakConceptQuiz", () => {
  it("grades each answer, explains it, and records the finished quiz once", async () => {
    vi.mocked(createWeakConceptQuiz).mockResolvedValue(QUIZ);
    vi.mocked(recordWeakConceptQuiz).mockResolvedValue({ correct: false, status: "practicing" });
    const onRecorded = vi.fn();

    render(
      <WeakConceptQuiz courseId="course-1" memoryId="memory-1" onClose={vi.fn()} onRecorded={onRecorded} />
    );

    expect(await screen.findByText("소프트맥스의 출력은 합이 1이다.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "O, 맞다" }));
    expect(screen.getByText("정답이에요")).toBeInTheDocument();
    expect(screen.getByText("근거: 3주차.pdf p.12")).toBeInTheDocument();
    // A second click cannot change an answer already given.
    expect(screen.getByRole("button", { name: "X, 틀리다" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "다음 문제" }));

    fireEvent.click(screen.getByRole("button", { name: "O, 맞다" }));
    expect(screen.getByText("아쉬워요. 정답은 X예요")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "결과 보기" }));

    expect(screen.getByText("2문제 중 1개 맞혔어요.")).toBeInTheDocument();
    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1));
    expect(recordWeakConceptQuiz).toHaveBeenCalledTimes(1);
    expect(recordWeakConceptQuiz).toHaveBeenCalledWith("course-1", "memory-1", 1, 2);
    expect(await screen.findByText(/내일 다시 물어볼게요/)).toBeInTheDocument();
  });

  it("says so when the quiz cannot be written", async () => {
    const { ApiError } = await import("../../lib/api");
    vi.mocked(createWeakConceptQuiz).mockRejectedValue(
      new ApiError(502, "퀴즈를 만들지 못했어요. 잠시 후 다시 시도해 주세요.")
    );
    const onClose = vi.fn();

    render(<WeakConceptQuiz courseId="course-1" memoryId="memory-1" onClose={onClose} onRecorded={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("퀴즈를 만들지 못했어요");
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(onClose).toHaveBeenCalled();
  });
});
