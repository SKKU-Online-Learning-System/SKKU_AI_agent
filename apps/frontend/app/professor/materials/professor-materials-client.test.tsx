// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import { ProfessorMaterialsClient } from "./professor-materials-client";

const apiMocks = vi.hoisted(() => ({
  deleteCourseMaterial: vi.fn(),
  listCourseMaterials: vi.fn(),
  listCourses: vi.fn(),
  uploadCourseMaterial: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    deleteCourseMaterial: apiMocks.deleteCourseMaterial,
    listCourseMaterials: apiMocks.listCourseMaterials,
    listCourses: apiMocks.listCourses,
    uploadCourseMaterial: apiMocks.uploadCourseMaterial
  };
});

const course = {
  id: "course-1",
  code: "AI101",
  title: "인공지능개론",
  term: "2026-2",
  instructorId: "professor-1",
  agentStatus: "active" as const,
  createdAt: "2026-07-20T00:00:00Z",
  updatedAt: "2026-07-20T00:00:00Z"
};

const material = {
  id: "material-1",
  courseId: "course-1",
  uploadedBy: "professor-1",
  originalFileName: "lecture.txt",
  fileType: "txt",
  fileSize: 1024,
  processingStatus: "completed" as const,
  processingError: null,
  createdAt: "2026-07-20T00:00:00Z",
  updatedAt: "2026-07-20T00:00:00Z"
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function arrangeLoadedMaterials() {
  apiMocks.listCourses.mockResolvedValue([course]);
  apiMocks.listCourseMaterials.mockResolvedValue([material]);
}

describe("ProfessorMaterialsClient", () => {
  it("loads the first course and its materials", async () => {
    arrangeLoadedMaterials();

    render(<ProfessorMaterialsClient />);

    expect(await screen.findByRole("option", { name: "AI101 인공지능개론" })).toBeInTheDocument();
    expect(apiMocks.listCourseMaterials).toHaveBeenCalledWith("course-1");
    expect(await screen.findByText("lecture.txt")).toBeInTheDocument();
    expect(screen.getByText("처리 완료")).toBeInTheDocument();
  });

  it("uploads a selected TXT file and adds the pending material", async () => {
    arrangeLoadedMaterials();
    apiMocks.uploadCourseMaterial.mockResolvedValue({
      ...material,
      id: "material-2",
      originalFileName: "week-2.txt",
      processingStatus: "pending"
    });
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    const file = new File(["week two"], "week-2.txt", { type: "text/plain" });

    fireEvent.change(screen.getByLabelText("강의자료 파일"), {
      target: { files: [file] }
    });
    fireEvent.click(screen.getByRole("button", { name: "업로드" }));

    await waitFor(() =>
      expect(apiMocks.uploadCourseMaterial).toHaveBeenCalledWith("course-1", file)
    );
    expect(await screen.findByText("week-2.txt")).toBeInTheDocument();
    expect(screen.getByText("처리 대기")).toBeInTheDocument();
  });

  it("deletes a material from the list only after the API succeeds", async () => {
    arrangeLoadedMaterials();
    apiMocks.deleteCourseMaterial.mockResolvedValue(undefined);
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");

    fireEvent.click(screen.getByRole("button", { name: "lecture.txt 삭제" }));

    await waitFor(() =>
      expect(apiMocks.deleteCourseMaterial).toHaveBeenCalledWith(
        "course-1",
        "material-1"
      )
    );
    await waitFor(() =>
      expect(screen.queryByText("lecture.txt")).not.toBeInTheDocument()
    );
  });

  it.each([
    [new File(["image"], "diagram.png", { type: "image/png" }), "지원하지 않는 파일 형식입니다."],
    [
      new File([new Uint8Array(20 * 1024 * 1024 + 1)], "large.txt", {
        type: "text/plain"
      }),
      "파일 크기는 20MB 이하여야 합니다."
    ]
  ])("rejects invalid files before upload", async (file, expectedMessage) => {
    arrangeLoadedMaterials();
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");

    fireEvent.change(screen.getByLabelText("강의자료 파일"), {
      target: { files: [file] }
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(expectedMessage);
    expect(apiMocks.uploadCourseMaterial).not.toHaveBeenCalled();
  });

  it("renders a backend upload error as an alert", async () => {
    arrangeLoadedMaterials();
    apiMocks.uploadCourseMaterial.mockRejectedValue(
      new ApiError(422, "파일 내용을 읽을 수 없습니다.")
    );
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    const file = new File(["broken"], "broken.txt", { type: "text/plain" });

    fireEvent.change(screen.getByLabelText("강의자료 파일"), {
      target: { files: [file] }
    });
    fireEvent.click(screen.getByRole("button", { name: "업로드" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "파일 내용을 읽을 수 없습니다."
    );
  });
});
