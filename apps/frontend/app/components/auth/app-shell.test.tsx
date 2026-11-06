// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

const mocks = vi.hoisted(() => ({
  pathname: { value: "/student/courses" },
  replace: vi.fn(),
  logout: vi.fn()
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname.value,
  useRouter: () => ({ replace: mocks.replace })
}));

vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    logout: mocks.logout,
    user: {
      id: "student-1",
      name: "Student",
      email: "student@skku.edu",
      role: "student"
    }
  })
}));

afterEach(() => {
  cleanup();
  mocks.pathname.value = "/student/courses";
  mocks.logout.mockClear();
  mocks.replace.mockClear();
});

describe("AppShell", () => {
  it("renders the SKKU header with the role menu and the active tab", () => {
    render(<AppShell><p>Course content</p></AppShell>);

    expect(screen.getByAltText("성균관대학교")).toBeInTheDocument();
    const studentMenu = screen.getByRole("navigation", { name: "학생 메뉴" });
    expect(within(studentMenu).getByRole("link", { name: "내 과목" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(screen.getByRole("banner")).getByText("Student")).toBeInTheDocument();
    expect(screen.getByText("Course content")).toBeInTheDocument();
  });

  it("logs out and returns to login", () => {
    render(<AppShell><p>Content</p></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(mocks.logout).toHaveBeenCalledTimes(1);
    expect(mocks.replace).toHaveBeenCalledWith("/login");
  });

  it("renders a student's course page bare: the study view brings its own bar", () => {
    mocks.pathname.value = "/student/courses/course-1";
    render(<AppShell><p>Study view</p></AppShell>);

    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.getByText("Study view")).toBeInTheDocument();
  });
});
