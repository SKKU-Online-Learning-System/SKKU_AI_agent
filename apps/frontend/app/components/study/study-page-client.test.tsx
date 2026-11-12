// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StudyPageClient } from "./study-page-client";

const mocks = vi.hoisted(() => ({
  agent: vi.fn(),
  getMaterialPageNote: vi.fn(),
  listCourses: vi.fn(),
  listCourseMaterials: vi.fn(),
  listMaterialPages: vi.fn(),
  fetchMaterialPageImage: vi.fn(),
  search: { value: "" }
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mocks.search.value)
}));

vi.mock("../auth/auth-provider", () => ({
  useAuth: () => ({
    logout: vi.fn(),
    user: { id: "student-1", name: "학생", email: "s@skku.edu", role: "student" }
  })
}));

vi.mock("../course-agent/course-agent-client", () => ({
  CourseAgentClient: (props: unknown) => {
    mocks.agent(props);
    return <div data-testid="agent" />;
  }
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    fetchMaterialPageImage: mocks.fetchMaterialPageImage,
    getMaterialPageNote: mocks.getMaterialPageNote,
    listCourseMaterials: mocks.listCourseMaterials,
    listCourses: mocks.listCourses,
    listMaterialPages: mocks.listMaterialPages
  };
});

const material = (id: string, week: number, name: string, status = "completed") => ({
  id,
  courseId: "course-1",
  uploadedBy: "p",
  originalFileName: name,
  fileType: "pdf",
  fileSize: 1024,
  week,
  processingStatus: status,
  processingError: null,
  chunkCount: 2,
  pageProgress: null,
  createdAt: "2026-09-01T00:00:00Z",
  updatedAt: "2026-09-01T00:00:00Z"
});

beforeEach(() => {
  mocks.listCourses.mockResolvedValue([
    {
      id: "course-1",
      code: "SWE3033",
      title: "운영체제",
      term: "2026-2",
      instructorId: "p",
      instructorName: "신동군",
      agentStatus: "active",
      createdAt: "",
      updatedAt: ""
    }
  ]);
  mocks.listCourseMaterials.mockResolvedValue([
    material("m2", 2, "week2.pdf"),
    material("m1", 1, "week1.pdf"),
    material("m3", 3, "week3.pdf", "processing")
  ]);
  mocks.listMaterialPages.mockImplementation((courseId: string, materialId: string) =>
    Promise.resolve({ material_id: materialId, file: "x.pdf", pages: [1, 2] })
  );
  mocks.fetchMaterialPageImage.mockResolvedValue(new Blob(["img"], { type: "image/jpeg" }));
  mocks.getMaterialPageNote.mockImplementation((courseId: string, materialId: string, page: number) =>
    Promise.resolve({
      material_id: materialId,
      page,
      title: `${materialId} ${page}쪽 제목`,
      summary: "핵심 문장",
      points: [{ label: "PFN", text: "물리 프레임 번호" }],
      pitfalls: ""
    })
  );
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: () => "blob:x" });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: () => undefined });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mocks.search.value = "";
});

describe("StudyPageClient", () => {
  it("opens the earliest week's 교안 with its note and lists the curriculum by week", async () => {
    render(<StudyPageClient courseId="course-1" />);

    expect(await screen.findByText("m1 1쪽 제목")).toBeInTheDocument();
    expect(screen.getByText("핵심 문장")).toBeInTheDocument();
    expect(screen.getByText("PFN")).toBeInTheDocument();
    const curriculum = screen.getByRole("region", { name: "커리큘럼" });
    const headings = within(curriculum).getAllByRole("button", { expanded: true });
    expect(headings.map((node) => node.textContent)).toEqual([
      "1주차1개 교안 · 2쪽",
      "2주차1개 교안 · 2쪽",
      "3주차1개 교안 · 2쪽"
    ]);
    expect(within(curriculum).getByRole("button", { name: /^week3\.pdf PDF/ })).toBeDisabled();
    expect(screen.getByText("3개 주차")).toBeInTheDocument();
  });

  it("moves between pages and 교안 from the pager and the curriculum", async () => {
    render(<StudyPageClient courseId="course-1" />);
    await screen.findByText("m1 1쪽 제목");

    fireEvent.click(screen.getByRole("button", { name: "다음 →" }));
    expect(await screen.findByText("m1 2쪽 제목")).toBeInTheDocument();
    expect(mocks.getMaterialPageNote).toHaveBeenLastCalledWith("course-1", "m1", 2);

    fireEvent.click(screen.getByRole("button", { name: /^week2\.pdf PDF/ }));
    expect(await screen.findByText("m2 1쪽 제목")).toBeInTheDocument();
    expect(screen.getByText("2주차 · week2.pdf")).toBeInTheDocument();
  });

  it("opens COURSE AGENT in the drawer with the page the student is reading", async () => {
    mocks.search.value = "panel=agent&sessionId=session-9";
    render(<StudyPageClient courseId="course-1" />);

    await screen.findByText("m1 1쪽 제목");
    expect(screen.getByTestId("agent")).toBeInTheDocument();
    const props = mocks.agent.mock.calls.at(-1)?.[0] as {
      embedded: boolean;
      focus: { materialId: string; page: number; label: string } | null;
      initialSessionId: string | null;
    };
    expect(props.embedded).toBe(true);
    expect(props.initialSessionId).toBe("session-9");
    expect(props.focus).toEqual({ materialId: "m1", page: 1, label: "week1.pdf p.1" });

    fireEvent.click(screen.getByRole("button", { name: "커리큘럼" }));
    expect(screen.queryByTestId("agent")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "커리큘럼" })).toBeInTheDocument();
  });
});
