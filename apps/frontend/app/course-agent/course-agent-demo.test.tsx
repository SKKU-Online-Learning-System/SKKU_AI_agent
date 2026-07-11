// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CourseAgentDemo from "./course-agent-demo";

const settingsKey = "skku-course-agent-settings-v1";

function roleButton(name: "학생" | "교수") {
  return screen.getByRole("button", { name });
}

function submitButton() {
  return screen.getByRole("button", { name: "질문 보내기" });
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => "attachment-id") });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("CourseAgentDemo client interactions", () => {
  it("switches unrestricted roles and retains the student personality", () => {
    render(<CourseAgentDemo />);

    fireEvent.click(screen.getByRole("radio", { name: /친근함/ }));
    fireEvent.click(roleButton("교수"));

    expect(roleButton("교수")).toHaveAttribute("aria-pressed", "true");
    expect(roleButton("학생")).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "전체 선택" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /친근함/ })).not.toBeInTheDocument();

    fireEvent.click(roleButton("학생"));

    expect(roleButton("학생")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("radio", { name: /친근함/ })).toBeChecked();
  });

  it("hydrates and persists only the allowed serializable settings", async () => {
    localStorage.setItem(
      settingsKey,
      JSON.stringify({
        activeRole: "professor",
        student: { personality: "friendly", messages: ["do not restore"] },
        professor: {
          selectedMaterialIds: [],
          attachments: [{ name: "do-not-restore.pdf" }]
        },
        secret: "do not persist"
      })
    );

    render(<CourseAgentDemo />);

    await waitFor(() => expect(roleButton("교수")).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByRole("checkbox", { name: /1주차 강의자료/ })).not.toBeChecked();
    expect(screen.queryByText("do-not-restore.pdf")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem(settingsKey) ?? "{}")).toEqual({
        activeRole: "professor",
        student: { personality: "friendly" },
        professor: { selectedMaterialIds: [] }
      });
    });
  });

  it("safely defaults when persisted JSON is malformed", async () => {
    localStorage.setItem(settingsKey, "{not-json");

    render(<CourseAgentDemo />);

    expect(roleButton("학생")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("radio", { name: /기본/ })).toBeChecked();
    await waitFor(() =>
      expect(() => JSON.parse(localStorage.getItem(settingsKey) ?? "")).not.toThrow()
    );
  });

  it("uses the selected student personality and renders citations on submit", () => {
    render(<CourseAgentDemo />);
    fireEvent.click(screen.getByRole("radio", { name: /친근함/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "질문" }), {
      target: { value: "RAG를 설명해 주세요" }
    });

    fireEvent.click(submitButton());

    expect(screen.getByText(/\[친근함\].*RAG를 설명해 주세요/)).toBeInTheDocument();
    expect(screen.getAllByText(/2주차 RAG 개요 p\.7/)).toHaveLength(2);
  });

  it("reports professor selected and attached material counts", () => {
    render(<CourseAgentDemo />);
    fireEvent.click(roleButton("교수"));
    const upload = screen.getByLabelText("파일 첨부");
    fireEvent.change(upload, {
      target: { files: [new File(["notes"], "notes.txt", { type: "text/plain" })] }
    });
    fireEvent.change(screen.getByRole("textbox", { name: "질문" }), {
      target: { value: "자료를 점검해 주세요" }
    });

    fireEvent.click(submitButton());

    expect(screen.getByText(/선택한 강의자료 1개와 첨부 자료 1개/)).toBeInTheDocument();
  });

  it("marks a professor response insufficient when no context is selected", () => {
    render(<CourseAgentDemo />);
    fireEvent.click(roleButton("교수"));
    fireEvent.click(screen.getByRole("button", { name: "전체 해제" }));
    fireEvent.change(screen.getByRole("textbox", { name: "질문" }), {
      target: { value: "답을 알려 주세요" }
    });

    fireEvent.click(submitButton());

    const response = screen.getByText(/강의자료가 없어/).closest("article");
    expect(response).toHaveAttribute("data-insufficient", "true");
  });

  it("allows an attachment-only submission", () => {
    render(<CourseAgentDemo />);
    expect(submitButton()).toBeDisabled();

    fireEvent.change(screen.getByLabelText("파일 첨부"), {
      target: { files: [new File(["question"], "question.txt", { type: "text/plain" })] }
    });

    expect(submitButton()).toBeEnabled();
    fireEvent.click(submitButton());
    const history = screen.getByRole("generic", { name: "질의응답 내역" });
    expect(within(history).getByText("첨부한 자료를 분석해 주세요.")).toBeInTheDocument();
  });
});
