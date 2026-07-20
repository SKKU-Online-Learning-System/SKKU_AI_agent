// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminCoursesClient } from "./admin-courses-client";

const apiMocks = vi.hoisted(() => ({
  activateAdminCourse: vi.fn(),
  deactivateAdminCourse: vi.fn(),
  listAdminCourses: vi.fn(),
  listAdminUsers: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    activateAdminCourse: apiMocks.activateAdminCourse,
    deactivateAdminCourse: apiMocks.deactivateAdminCourse,
    listAdminCourses: apiMocks.listAdminCourses,
    listAdminUsers: apiMocks.listAdminUsers
  };
});

const activeCourse = {
  id: "course-1",
  name: "인공지능개론",
  semester: "2026-2",
  description: "AI 기본 개념",
  professorId: "professor-1",
  professorName: "김교수",
  isActive: true,
  studentAccessCount: 3,
  createdAt: "2026-07-20T00:00:00.000Z",
  updatedAt: "2026-07-20T00:00:00.000Z"
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminCoursesClient", () => {
  it("renders admin courses and toggles active state", async () => {
    apiMocks.listAdminCourses.mockResolvedValue([activeCourse]);
    apiMocks.listAdminUsers.mockResolvedValue([
      {
        id: "professor-1",
        name: "김교수",
        email: "professor@skku.edu",
        role: "professor",
        department: null,
        createdAt: "2026-07-20T00:00:00.000Z",
        updatedAt: "2026-07-20T00:00:00.000Z"
      }
    ]);
    apiMocks.deactivateAdminCourse.mockResolvedValue({
      ...activeCourse,
      isActive: false
    });

    render(<AdminCoursesClient />);

    expect(await screen.findByText("인공지능개론")).toBeInTheDocument();
    expect(screen.getAllByText("김교수")).toHaveLength(2);
    expect(screen.getByText("3명")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "새 과목" })).toHaveAttribute(
      "href",
      "/admin/courses/new"
    );

    fireEvent.click(screen.getByRole("button", { name: "비활성화" }));

    await waitFor(() => expect(apiMocks.deactivateAdminCourse).toHaveBeenCalledWith("course-1"));
    await waitFor(() => expect(screen.getAllByText("비활성").length).toBeGreaterThan(1));
  });
});
