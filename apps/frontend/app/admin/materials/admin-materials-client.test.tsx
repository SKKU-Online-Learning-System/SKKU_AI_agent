// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminMaterialsClient } from "./admin-materials-client";

const mocks = vi.hoisted(() => ({ listAdminCourses: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, listAdminCourses: mocks.listAdminCourses };
});

vi.mock("../../components/courses/course-materials-client", () => ({
  CourseMaterialsClient: ({ courseId }: { courseId: string }) => <p>연동 과목 {courseId}</p>
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminMaterialsClient", () => {
  it("connects the selected admin course to the real course materials view", async () => {
    mocks.listAdminCourses.mockResolvedValue([
      {
        id: "course-1",
        name: "인공지능개론",
        semester: "2026-2",
        professorId: "professor-1",
        professorName: "김교수",
        isActive: true,
        studentAccessCount: 1,
        createdAt: "2026-07-21T00:00:00Z",
        updatedAt: "2026-07-21T00:00:00Z"
      }
    ]);

    render(<AdminMaterialsClient />);

    expect(await screen.findByText("연동 과목 course-1")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "인공지능개론 · 2026-2" })).toBeInTheDocument();
  });
});
