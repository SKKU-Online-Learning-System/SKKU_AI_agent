// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { AdminScreen } from "./admin-screens";
import { ProfessorScreen } from "./professor-screens";
import { StudentScreen } from "./student-screens";

afterEach(cleanup);

describe("role screens", () => {
  it("renders source and learning guidance in student chat", () => {
    render(<StudentScreen screen="student-chat" />);

    expect(screen.getByText(/2주차 RAG 개요/)).toBeInTheDocument();
    expect(screen.getByText(/AI 답변은 학습 보조용/)).toBeInTheDocument();
  });

  it("renders professor material processing states", () => {
    render(<ProfessorScreen screen="professor-materials" />);

    expect(screen.getByText("처리 중")).toBeInTheDocument();
    expect(screen.getByText("실패")).toBeInTheDocument();
  });

  it("filters administrator users by role", () => {
    render(<AdminScreen screen="admin-users" />);
    fireEvent.change(screen.getByLabelText("역할 필터"), {
      target: { value: "professor" }
    });

    expect(screen.getByText("김교수")).toBeInTheDocument();
    expect(screen.queryByText("박학생")).not.toBeInTheDocument();
  });
});
