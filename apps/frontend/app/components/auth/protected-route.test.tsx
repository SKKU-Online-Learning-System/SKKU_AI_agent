// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthUser } from "../../lib/auth";
import { ProtectedRoute } from "./protected-route";

const mocks = vi.hoisted(() => ({
  authState: {
    value: { status: "loading", user: null } as {
      status: "loading" | "authenticated" | "unauthenticated";
      user: AuthUser | null;
    }
  },
  pathname: { value: "/admin" },
  replace: vi.fn()
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname.value,
  useRouter: () => ({ replace: mocks.replace })
}));

vi.mock("./auth-provider", () => ({
  useAuth: () => mocks.authState.value
}));

afterEach(() => {
  cleanup();
  mocks.replace.mockClear();
  mocks.pathname.value = "/admin";
});

describe("ProtectedRoute", () => {
  it("redirects unauthenticated users to login with the current path", () => {
    mocks.authState.value = { status: "unauthenticated", user: null };

    render(
      <ProtectedRoute allowedRoles={["admin"]}>
        <p>Admin content</p>
      </ProtectedRoute>
    );

    expect(mocks.replace).toHaveBeenCalledWith("/login?next=%2Fadmin");
  });

  it("redirects authenticated users without the required role", () => {
    mocks.authState.value = {
      status: "authenticated",
      user: {
        id: "student-1",
        name: "Student",
        email: "student@skku.edu",
        role: "student"
      }
    };

    render(
      <ProtectedRoute allowedRoles={["admin"]}>
        <p>Admin content</p>
      </ProtectedRoute>
    );

    expect(mocks.replace).toHaveBeenCalledWith("/forbidden");
  });

  it("renders children when the user has the required role", () => {
    mocks.authState.value = {
      status: "authenticated",
      user: {
        id: "admin-1",
        name: "Admin",
        email: "admin@skku.edu",
        role: "admin"
      }
    };

    render(
      <ProtectedRoute allowedRoles={["admin"]}>
        <p>Admin content</p>
      </ProtectedRoute>
    );

    expect(screen.getByText("Admin content")).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});
