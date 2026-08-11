// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CourseWorkspaceClient } from "./course-workspace-client";

const mocks = vi.hoisted(() => ({
  listCourses: vi.fn(),
  logout: vi.fn(),
  pathname: { value: "/student/courses/course-1/materials" },
  replace: vi.fn()
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname.value,
  useRouter: () => ({ replace: mocks.replace })
}));

vi.mock("../auth/auth-provider", () => ({
  useAuth: () => ({
    logout: mocks.logout,
    user: { id: "student-1", name: "Student", email: "student@skku.edu", role: "student" }
  })
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
    expect(screen.getByText(/2026-2/)).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "과목 메뉴" });
    expect(within(navigation).getByRole("link", { name: "홈" })).toHaveAttribute(
      "href",
      "/student/courses/course-1"
    );
    expect(within(navigation).getByRole("link", { name: "강의콘텐츠" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    // COURSE AGENT replaces the old separate "AI 질문" tab.
    expect(within(navigation).queryByText("AI 질문")).not.toBeInTheDocument();
    expect(within(navigation).getByRole("link", { name: "COURSE AGENT" })).toHaveAttribute(
      "href",
      "/student/courses/course-1/course-agent"
    );
  });

  it("renders the inactive i-Campus course tools alongside the live ones", async () => {
    mocks.listCourses.mockResolvedValue([]);

    render(
      <CourseWorkspaceClient courseId="course-1" role="student">
        <h1>강의자료</h1>
      </CourseWorkspaceClient>
    );

    const navigation = await screen.findByRole("navigation", { name: "과목 메뉴" });
    ["수업 계획서", "공지", "게시판", "과제 및 평가", "시험 및 설문", "출결현황", "학습 활동 현황", "성적"].forEach(
      (label) => {
        expect(within(navigation).getByText(label)).toBeInTheDocument();
        expect(within(navigation).queryByRole("link", { name: label })).not.toBeInTheDocument();
      }
    );
  });

  it("links professors to course-scoped RAG debug", async () => {
    mocks.pathname.value = "/professor/courses/course-1/rag-debug";
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

    render(
      <CourseWorkspaceClient courseId="course-1" role="professor">
        <h1>RAG 검색 디버그</h1>
      </CourseWorkspaceClient>
    );

    const navigation = await screen.findByRole("navigation", { name: "과목 메뉴" });
    expect(within(navigation).getByRole("link", { name: "RAG 디버그" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });
});
