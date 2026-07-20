// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import { CourseListClient } from "./course-list-client";

const apiMocks = vi.hoisted(() => ({
  listCourses: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    listCourses: apiMocks.listCourses
  };
});

const activeCourse = {
  id: "course-1",
  code: "course-1",
  title: "인공지능개론",
  term: "2026-2",
  instructorId: "professor-1",
  agentStatus: "active" as const,
  createdAt: "2026-07-20T00:00:00Z",
  updatedAt: "2026-07-20T00:00:00Z"
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CourseListClient", () => {
  it("renders courses returned for the current role", async () => {
    apiMocks.listCourses.mockResolvedValue([activeCourse]);

    render(<CourseListClient audience="student" />);

    expect(await screen.findByText("인공지능개론")).toBeInTheDocument();
    expect(screen.getByText("2026-2")).toBeInTheDocument();
    expect(screen.getByText("활성")).toBeInTheDocument();
  });

  it.each([
    ["student", "수강 중인 과목이 없습니다."],
    ["professor", "담당 과목이 없습니다."]
  ] as const)("renders the %s empty state", async (audience, emptyMessage) => {
    apiMocks.listCourses.mockResolvedValue([]);

    render(<CourseListClient audience={audience} />);

    expect(await screen.findByText(emptyMessage)).toBeInTheDocument();
  });

  it("renders an API error as an alert", async () => {
    apiMocks.listCourses.mockRejectedValue(new ApiError(403, "과목 조회 권한이 없습니다."));

    render(<CourseListClient audience="professor" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "과목 조회 권한이 없습니다."
    );
  });
});
