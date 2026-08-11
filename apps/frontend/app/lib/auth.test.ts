import { describe, expect, it } from "vitest";
import { canAccessRole, getRoleHomePath, getRoleMenuItems } from "./auth";

describe("auth route policy", () => {
  it("maps every role to its dashboard", () => {
    expect(getRoleHomePath("admin")).toBe("/admin");
    expect(getRoleHomePath("professor")).toBe("/professor");
    expect(getRoleHomePath("student")).toBe("/student");
  });

  it("returns role-specific menu items", () => {
    expect(getRoleMenuItems("admin")).toEqual([
      { href: "/admin", label: "대시보드", icon: "dashboard" },
      { href: "/admin/courses", label: "과목", icon: "course" },
      { href: "/admin/users", label: "사용자", icon: "group" },
      { href: "/admin/materials", label: "자료", icon: "material" },
      { href: "/admin/logs", label: "질문 로그", icon: "agent" }
    ]);
    expect(getRoleMenuItems("professor")).toEqual([
      { href: "/professor", label: "대시보드", icon: "dashboard" },
      { href: "/professor/courses", label: "해당 과목", icon: "course" },
      { href: "/professor/materials", label: "강의자료", icon: "material" },
      { href: "/professor/logs", label: "질문 로그", icon: "agent" },
      { href: "/professor/rag-debug", label: "RAG 디버그", icon: "source" }
    ]);
    expect(getRoleMenuItems("student")).toEqual([
      { href: "/student", label: "대시보드", icon: "dashboard" },
      { href: "/student/courses", label: "내 과목", icon: "course" },
      { href: "/student/chat-history", label: "대화 이력", icon: "material" }
    ]);
  });

  it("checks role access", () => {
    expect(canAccessRole("admin", ["admin"])).toBe(true);
    expect(canAccessRole("student", ["admin"])).toBe(false);
    expect(canAccessRole("professor", ["admin"])).toBe(false);
  });
});
