// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CourseMaterial } from "../../lib/api";
import { WeeklyMaterialList } from "./weekly-material-list";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, downloadCourseMaterial: vi.fn() };
});

const material: CourseMaterial = {
  id: "material-1",
  courseId: "course-1",
  uploadedBy: "professor-1",
  originalFileName: "week-3.pdf",
  fileType: "pdf",
  fileSize: 2048,
  week: 3,
  processingStatus: "completed",
  processingError: null,
  createdAt: "2026-07-21T00:00:00Z",
  updatedAt: "2026-07-21T00:00:00Z"
};

afterEach(cleanup);

describe("WeeklyMaterialList", () => {
  it("matches the Canvas lecture-content structure with 16 shortcuts and accordions", () => {
    render(<WeeklyMaterialList courseId="course-1" materials={[material]} />);

    const shortcuts = screen.getByRole("navigation", { name: "주차 바로가기" });
    expect(shortcuts.querySelectorAll("button")).toHaveLength(16);
    expect(screen.getByRole("button", { name: /3주차 1개 자료/ })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(screen.getByText("week-3.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^1주차 0개 자료$/ }));
    expect(screen.getByText("등록된 강의자료가 없습니다.")).toBeInTheDocument();
  });
});
