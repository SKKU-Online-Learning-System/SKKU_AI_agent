import { describe, expect, it } from "vitest";
import {
  courseNavItems,
  dashboardMetrics,
  demoCourses,
  demoLogs,
  materials,
  personalityOptions
} from "./demo-data";

describe("course agent demo data", () => {
  it("provides the seven personality options in the specified order", () => {
    expect(personalityOptions.map((option) => option.id)).toEqual([
      "default",
      "professional",
      "friendly",
      "candid",
      "quirky",
      "efficient",
      "cynical"
    ]);
  });

  it("activates only AI 코스 에이전트 in the course navigation", () => {
    expect(courseNavItems.map(({ label, active }) => ({ label, active: Boolean(active) }))).toEqual([
      { label: "홈", active: false },
      { label: "강의콘텐츠", active: false },
      { label: "출결현황", active: false },
      { label: "성적", active: false },
      { label: "AI 코스 에이전트", active: true }
    ]);
  });

  it("covers PRD states required by the role screens", () => {
    expect(demoCourses.some((course) => course.agentStatus === "disabled")).toBe(true);
    expect(materials.map((material) => material.status)).toEqual(
      expect.arrayContaining(["ready", "processing", "failed"])
    );
    expect(demoLogs[0]).toMatchObject({
      role: expect.any(String),
      responseTime: expect.any(Number)
    });
    expect(dashboardMetrics.length).toBeGreaterThanOrEqual(5);
  });
});
