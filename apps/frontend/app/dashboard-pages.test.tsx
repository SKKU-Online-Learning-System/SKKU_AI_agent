// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminDashboardPage from "./admin/page";
import ProfessorDashboardPage from "./professor/page";
import StudentDashboardPage from "./student/page";

vi.mock("./components/courses/course-list-client", () => ({
  CourseListClient: ({ audience }: { audience: "professor" | "student" }) => (
    <div data-testid={`course-list-${audience}`} />
  )
}));

vi.mock("./admin/courses/admin-courses-client", () => ({
  AdminCoursesClient: () => <div data-testid="admin-course-management" />
}));

afterEach(cleanup);

describe("role dashboard pages", () => {
  it("shows the student's accessible courses", () => {
    render(<StudentDashboardPage />);
    expect(screen.getByTestId("course-list-student")).toBeInTheDocument();
  });

  it("shows the professor's assigned courses", () => {
    render(<ProfessorDashboardPage />);
    expect(screen.getByTestId("course-list-professor")).toBeInTheDocument();
  });

  it("shows full course management for the administrator", () => {
    render(<AdminDashboardPage />);
    expect(screen.getByTestId("admin-course-management")).toBeInTheDocument();
  });
});
