// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CourseDashboardClient } from "./course-dashboard-client";

const apiMocks = vi.hoisted(() => ({
  listAdminCourses: vi.fn(),
  listCourses: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    listAdminCourses: apiMocks.listAdminCourses,
    listCourses: apiMocks.listCourses
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CourseDashboardClient", () => {
  it("renders each student course as a Canvas-style course card link", async () => {
    apiMocks.listCourses.mockResolvedValue([
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

    render(<CourseDashboardClient audience="student" />);

    const card = await screen.findByRole("link", { name: /Introduction to Database/ });
    expect(card).toHaveAttribute("href", "/student/courses/course-1");
    expect(screen.getByText("SWE3003")).toBeInTheDocument();
    expect(screen.getByText("2026-2")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("links an administrator course card to its course workspace", async () => {
    apiMocks.listAdminCourses.mockResolvedValue([
      {
        id: "course-2",
        name: "인공지능개론",
        semester: "2026-2",
        description: "AI 기초",
        professorId: "professor-1",
        professorName: "김교수",
        isActive: true,
        studentAccessCount: 12,
        createdAt: "2026-07-20T00:00:00Z",
        updatedAt: "2026-07-20T00:00:00Z"
      }
    ]);

    render(<CourseDashboardClient audience="admin" />);

    expect(await screen.findByRole("link", { name: /인공지능개론/ })).toHaveAttribute(
      "href",
      "/admin/course/course-2"
    );
    expect(screen.getByText("수강 접근 12명")).toBeInTheDocument();
  });
});
