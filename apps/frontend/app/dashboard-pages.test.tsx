// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminDashboardPage from "./admin/page";
import ProfessorDashboardPage from "./professor/page";
import StudentDashboardPage from "./student/page";

vi.mock("./components/courses/course-dashboard-client", () => ({
  CourseDashboardClient: ({ audience }: { audience: "admin" | "professor" | "student" }) => (
    <div data-testid={`course-dashboard-${audience}`} />
  )
}));

afterEach(cleanup);

describe("role dashboard pages", () => {
  it("shows the student's accessible courses", () => {
    render(<StudentDashboardPage />);
    expect(screen.getByTestId("course-dashboard-student")).toBeInTheDocument();
  });

  it("shows the professor's assigned courses", () => {
    render(<ProfessorDashboardPage />);
    expect(screen.getByTestId("course-dashboard-professor")).toBeInTheDocument();
  });

  it("shows course cards for the administrator", () => {
    render(<AdminDashboardPage />);
    expect(screen.getByTestId("course-dashboard-admin")).toBeInTheDocument();
  });
});
