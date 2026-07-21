// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CourseWorkspaceClient } from "./course-workspace-client";

const mocks = vi.hoisted(() => ({
  listCourses: vi.fn(),
  pathname: { value: "/student/courses/course-1/materials" }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname.value
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, listCourses: mocks.listCourses };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mocks.pathname.value = "/student/courses/course-1/materials";
});

describe("CourseWorkspaceClient", () => {
  it("keeps the course title and course navigation around the selected tab", async () => {
    mocks.listCourses.mockResolvedValue([
      {
        id: "course-1",
        code: "SWE3003",
        title: "Introduction to Database",
        term: "2026-2",
        instructorId: "professor-1",
        instructorName: "남범석",
        agentStatus: "active",
        createdAt: "2026-07-20T00:00:00Z",
        updatedAt: "2026-07-20T00:00:00Z"
      }
    ]);

    render(
      <CourseWorkspaceClient courseId="course-1" role="student">
        <h1>강의자료</h1>
      </CourseWorkspaceClient>
    );

    expect(await screen.findByText("Introduction to Database")).toBeInTheDocument();
    expect(screen.getByText("2026-2")).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "과목 탐색 메뉴" });
    expect(within(navigation).getByRole("link", { name: "홈" })).toHaveAttribute(
      "href",
      "/student/courses/course-1"
    );
    expect(within(navigation).getByRole("link", { name: "강의콘텐츠" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(navigation).getByRole("link", { name: "AI 질문" })).toHaveAttribute(
      "href",
      "/student/courses/course-1/chat"
    );
  });
});
