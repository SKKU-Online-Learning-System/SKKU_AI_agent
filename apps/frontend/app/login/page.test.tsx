// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./page";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace })
}));

vi.mock("../components/auth/auth-provider", () => ({
  useAuth: () => ({
    login: mocks.login,
    status: "unauthenticated",
    user: null
  })
}));

afterEach(() => {
  cleanup();
  mocks.login.mockReset();
  mocks.replace.mockReset();
});

describe("LoginPage", () => {
  it("renders the local i-Campus brand and accessible credentials", () => {
    render(<LoginPage />);
    expect(screen.getByAltText("성균관대학교 i-Campus")).toHaveAttribute(
      "src",
      "/icampus-login-logo.png"
    );
    expect(screen.getByLabelText("아이디 또는 이메일")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "LOGIN" })).toBeInTheDocument();
  });

  it("uses the existing login contract and redirects by role", async () => {
    mocks.login.mockResolvedValue({
      id: "student-1",
      name: "Student",
      email: "student@skku.edu",
      role: "student"
    });
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText("아이디 또는 이메일"), {
      target: { value: "student@skku.edu" }
    });
    fireEvent.change(screen.getByLabelText("비밀번호"), {
      target: { value: "password123" }
    });
    fireEvent.click(screen.getByRole("button", { name: "LOGIN" }));
    await waitFor(() => {
      expect(mocks.login).toHaveBeenCalledWith("student@skku.edu", "password123");
      expect(mocks.replace).toHaveBeenCalledWith("/student");
    });
  });
});
