// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { RoleDashboard } from "./role-dashboard";

describe("RoleDashboard", () => {
  it("renders Canvas-style action cards as real links", () => {
    render(
      <RoleDashboard
        actions={[
          {
            description: "수강 과목을 확인합니다.",
            href: "/student/courses",
            icon: "course",
            label: "내 과목"
          }
        ]}
        description="학생 학습 화면입니다."
        title="대시보드"
      />
    );
    expect(screen.getByRole("heading", { name: "대시보드" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /내 과목/ })).toHaveAttribute(
      "href",
      "/student/courses"
    );
    expect(screen.getByText("수강 과목을 확인합니다.")).toBeInTheDocument();
  });
});
