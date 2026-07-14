import { describe, expect, it } from "vitest";
import { canAccessRole, getRoleHomePath, getRoleMenuItems } from "./auth";

describe("auth route policy", () => {
  it("maps every role to its dashboard", () => {
    expect(getRoleHomePath("admin")).toBe("/admin");
    expect(getRoleHomePath("professor")).toBe("/professor");
    expect(getRoleHomePath("student")).toBe("/student");
  });

  it("returns role-specific menu items", () => {
    expect(getRoleMenuItems("admin").map((item) => item.label)).toEqual([
      "관리자 대시보드",
      "과목 관리",
      "사용자 관리",
      "자료 관리"
    ]);
    expect(getRoleMenuItems("professor").map((item) => item.label)).toEqual([
      "교수자 대시보드",
      "담당 과목",
      "자료 업로드"
    ]);
    expect(getRoleMenuItems("student").map((item) => item.label)).toEqual([
      "학생 대시보드",
      "내 과목",
      "챗봇"
    ]);
  });

  it("checks role access", () => {
    expect(canAccessRole("admin", ["admin"])).toBe(true);
    expect(canAccessRole("student", ["admin"])).toBe(false);
    expect(canAccessRole("professor", ["admin"])).toBe(false);
  });
});
