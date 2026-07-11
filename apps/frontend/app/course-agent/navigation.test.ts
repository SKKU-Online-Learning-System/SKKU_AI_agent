import { describe, expect, it } from "vitest";
import { getDefaultScreen, roleNavigation } from "./navigation";

describe("roleNavigation", () => {
  it("lists only screens allowed for a role", () => {
    expect(roleNavigation.student.map((item) => item.id)).toContain("student-chat");
    expect(roleNavigation.student.map((item) => item.id)).not.toContain("admin-users");
    expect(roleNavigation.admin.map((item) => item.id)).toContain("admin-users");
  });

  it("returns a safe default for every role", () => {
    expect(getDefaultScreen("student")).toBe("student-chat");
    expect(getDefaultScreen("professor")).toBe("professor-dashboard");
    expect(getDefaultScreen("admin")).toBe("admin-dashboard");
  });
});
