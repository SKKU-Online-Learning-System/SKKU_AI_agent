// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import { ChatLogClient } from "./chat-log-client";

const api = vi.hoisted(() => ({ listCourses: vi.fn(), getCourseKeywordCounts: vi.fn() }));

vi.mock("../../lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../lib/api")>(),
  ...api
}));

beforeEach(() => {
  api.listCourses.mockResolvedValue([
    { id: "ai", title: "인공지능개론", term: "2026-2" },
    { id: "db", title: "데이터베이스", term: "2026-2" }
  ]);
  api.getCourseKeywordCounts.mockImplementation(async (courseId: string) => ({
    courseId,
    weeks: courseId === "ai" ? [
      { week: 2, keywords: [{ keyword: "경사하강법", questionCount: 6 }] }
    ] : []
  }));
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("course keyword statistics", () => {
  it("renders only week, approved keyword and question count", async () => {
    render(<ChatLogClient />);

    expect(await screen.findByRole("row", { name: "2주차 경사하강법 6건" }))
      .toBeInTheDocument();
    expect(api.getCourseKeywordCounts).toHaveBeenCalledWith("ai");
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent))
      .toEqual(["주차", "핵심 키워드", "질문 건수"]);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("drops the previous course's rows when switching courses", async () => {
    render(<ChatLogClient />);
    await screen.findByText("경사하강법");

    fireEvent.change(screen.getByLabelText("과목"), { target: { value: "db" } });

    expect(screen.queryByText("경사하강법")).not.toBeInTheDocument();
    expect(await screen.findByText("공개 기준을 충족한 키워드가 없습니다."))
      .toBeInTheDocument();
    expect(api.getCourseKeywordCounts).toHaveBeenLastCalledWith("db");
  });

  it("shows a safe error when course access is denied", async () => {
    api.getCourseKeywordCounts.mockRejectedValue(new ApiError(403, "internal detail"));
    render(<ChatLogClient />);

    expect(await screen.findByRole("alert")).toHaveTextContent("이 과목의 통계를 볼 수 없습니다.");
    expect(screen.queryByText("internal detail")).not.toBeInTheDocument();
  });
});
