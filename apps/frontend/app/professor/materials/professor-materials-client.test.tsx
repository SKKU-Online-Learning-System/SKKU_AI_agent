// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../lib/api";
import type { CourseMaterial } from "../../lib/api";
import { ProfessorMaterialsClient } from "./professor-materials-client";

const apiMocks = vi.hoisted(() => ({
  deleteCourseMaterial: vi.fn(),
  getCourseRagStatus: vi.fn(),
  listCourseMaterials: vi.fn(),
  listCourses: vi.fn(),
  processCourseMaterial: vi.fn(),
  reprocessCourseMaterial: vi.fn(),
  uploadCourseMaterial: vi.fn()
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return {
    ...actual,
    deleteCourseMaterial: apiMocks.deleteCourseMaterial,
    getCourseRagStatus: apiMocks.getCourseRagStatus,
    listCourseMaterials: apiMocks.listCourseMaterials,
    listCourses: apiMocks.listCourses,
    processCourseMaterial: apiMocks.processCourseMaterial,
    reprocessCourseMaterial: apiMocks.reprocessCourseMaterial,
    uploadCourseMaterial: apiMocks.uploadCourseMaterial
  };
});

const course = {
  id: "course-1",
  code: "AI101",
  title: "인공지능개론",
  term: "2026-2",
  instructorId: "professor-1",
  instructorName: "김교수",
  agentStatus: "active" as const,
  createdAt: "2026-07-20T00:00:00Z",
  updatedAt: "2026-07-20T00:00:00Z"
};

const secondCourse = {
  ...course,
  id: "course-2",
  code: "AI202",
  title: "기계학습개론"
};

const material: CourseMaterial = {
  id: "material-1",
  courseId: "course-1",
  uploadedBy: "professor-1",
  originalFileName: "lecture.txt",
  fileType: "txt",
  fileSize: 1024,
  week: 1,
  processingStatus: "completed",
  processingError: null,
  chunkCount: 3,
  createdAt: "2026-07-20T00:00:00Z",
  updatedAt: "2026-07-20T00:00:00Z"
};

const ragStatus = {
  courseId: "course-1",
  materialCount: 1,
  completedMaterialCount: 1,
  failedMaterialCount: 0,
  chunkCount: 3,
  embeddedChunkCount: 3,
  isSearchReady: true
};

beforeEach(() => {
  apiMocks.getCourseRagStatus.mockResolvedValue(ragStatus);
});

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function arrangeLoadedMaterials() {
  apiMocks.listCourses.mockResolvedValue([course]);
  apiMocks.listCourseMaterials.mockResolvedValue([material]);
}

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

describe("ProfessorMaterialsClient", () => {
  it("locks the material workspace to the course from the detail route", async () => {
    apiMocks.listCourseMaterials.mockResolvedValue([material]);

    render(<ProfessorMaterialsClient courseId="course-1" />);

    expect(await screen.findByText("lecture.txt")).toBeInTheDocument();
    expect(apiMocks.listCourseMaterials).toHaveBeenCalledWith("course-1");
    expect(apiMocks.listCourses).not.toHaveBeenCalled();
    expect(screen.queryByRole("combobox", { name: "과목" })).not.toBeInTheDocument();
  });

  it("loads the first course and its materials", async () => {
    arrangeLoadedMaterials();

    render(<ProfessorMaterialsClient />);

    expect(await screen.findByRole("option", { name: "AI101 인공지능개론" })).toBeInTheDocument();
    expect(apiMocks.listCourseMaterials).toHaveBeenCalledWith("course-1");
    expect(await screen.findByText("lecture.txt")).toBeInTheDocument();
    expect(screen.getByText("처리 완료")).toBeInTheDocument();
    expect(screen.getByText("청크 3개")).toBeInTheDocument();
    expect(screen.getByText("이 과목은 검색 준비 완료")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "lecture.txt 재처리" })).toBeEnabled();
  });

  it("adds an uploaded file as pending in the selected week", async () => {
    arrangeLoadedMaterials();
    apiMocks.uploadCourseMaterial.mockResolvedValue({
      ...material,
      id: "material-2",
      originalFileName: "week-2.txt",
      processingStatus: "pending",
      chunkCount: 0,
      week: 2
    });
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    fireEvent.change(screen.getByRole("combobox", { name: "주차" }), {
      target: { value: "2" }
    });
    const file = new File(["week two"], "week-2.txt", { type: "text/plain" });

    fireEvent.change(screen.getByLabelText("강의자료 파일"), {
      target: { files: [file] }
    });
    fireEvent.click(screen.getByRole("button", { name: "업로드" }));

    await waitFor(() =>
      expect(apiMocks.uploadCourseMaterial).toHaveBeenCalledWith("course-1", file, 2)
    );
    expect(await screen.findByText("week-2.txt")).toBeInTheDocument();
    expect(screen.getByText("처리 대기")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "week-2.txt 처리 시작" })).toBeEnabled();
  });

  it("uploads every selected file and processes the leftovers in one click", async () => {
    arrangeLoadedMaterials();
    const first = new File(["one"], "week-2a.txt", { type: "text/plain" });
    const second = new File(["two"], "week-2b.txt", { type: "text/plain" });
    apiMocks.uploadCourseMaterial
      .mockResolvedValueOnce({
        ...material,
        id: "material-2",
        originalFileName: first.name,
        processingStatus: "pending",
        chunkCount: 0,
        week: 2
      })
      .mockResolvedValueOnce({
        ...material,
        id: "material-3",
        originalFileName: second.name,
        processingStatus: "failed",
        chunkCount: 0,
        week: 2
      });
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    fireEvent.change(screen.getByRole("combobox", { name: "주차" }), {
      target: { value: "2" }
    });

    fireEvent.change(screen.getByLabelText("강의자료 파일"), {
      target: { files: [first, second] }
    });
    fireEvent.click(screen.getByRole("button", { name: "2개 업로드" }));

    await waitFor(() =>
      expect(apiMocks.uploadCourseMaterial).toHaveBeenCalledTimes(2)
    );
    expect(apiMocks.uploadCourseMaterial).toHaveBeenNthCalledWith(1, "course-1", first, 2);
    expect(apiMocks.uploadCourseMaterial).toHaveBeenNthCalledWith(2, "course-1", second, 2);

    fireEvent.click(
      await screen.findByRole("button", { name: "미처리 자료 2개 모두 처리" })
    );

    await waitFor(() =>
      expect(apiMocks.processCourseMaterial).toHaveBeenCalledWith("course-1", "material-2")
    );
    expect(apiMocks.reprocessCourseMaterial).toHaveBeenCalledWith("course-1", "material-3");
  });

  it("keeps a row until delete succeeds and blocks duplicate deletion", async () => {
    arrangeLoadedMaterials();
    const deletion = deferred<void>();
    apiMocks.deleteCourseMaterial.mockReturnValue(deletion.promise);
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");

    const deleteButton = screen.getByRole("button", { name: "lecture.txt 삭제" });
    fireEvent.click(deleteButton);
    fireEvent.click(deleteButton);

    expect(apiMocks.deleteCourseMaterial).toHaveBeenCalledTimes(1);
    expect(apiMocks.deleteCourseMaterial).toHaveBeenCalledWith(
      "course-1",
      "material-1"
    );
    expect(screen.getByText("lecture.txt")).toBeInTheDocument();
    expect(deleteButton).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "과목" })).toBeDisabled();

    await act(async () => {
      deletion.resolve();
      await deletion.promise;
    });

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
    const fileInput = screen.getByLabelText("강의자료 파일") as HTMLInputElement;
    Object.defineProperty(fileInput, "value", {
      configurable: true,
      value: `C:\\fakepath\\${file.name}`,
      writable: true
    });

    fireEvent.change(fileInput, {
      target: { files: [file] }
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(expectedMessage);
    expect(fileInput).toHaveValue("");
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

  it("resets the selected file and DOM input when the course changes", async () => {
    apiMocks.listCourses.mockResolvedValue([course, secondCourse]);
    apiMocks.listCourseMaterials
      .mockResolvedValueOnce([material])
      .mockResolvedValueOnce([]);
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    const fileInput = screen.getByLabelText("강의자료 파일") as HTMLInputElement;
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    Object.defineProperty(fileInput, "value", {
      configurable: true,
      value: "C:\\fakepath\\notes.txt",
      writable: true
    });
    fireEvent.change(fileInput, { target: { files: [file] } });
    expect(screen.getByRole("button", { name: "업로드" })).toBeEnabled();

    fireEvent.change(screen.getByRole("combobox", { name: "과목" }), {
      target: { value: "course-2" }
    });

    expect(fileInput).toHaveValue("");
    expect(screen.getByRole("button", { name: "업로드" })).toBeDisabled();
  });

  it("disables upload controls and shows loading while materials load", async () => {
    const materialList = deferred<typeof material[]>();
    apiMocks.listCourses.mockResolvedValue([course]);
    apiMocks.listCourseMaterials.mockReturnValue(materialList.promise);

    render(<ProfessorMaterialsClient />);

    expect(
      await screen.findByRole("option", { name: "AI101 인공지능개론" })
    ).toBeInTheDocument();
    expect(screen.getByLabelText("강의자료 파일")).toBeDisabled();
    expect(screen.getByRole("button", { name: "업로드" })).toBeDisabled();
    expect(screen.getByText("강의자료를 불러오고 있습니다.")).toBeInTheDocument();
    expect(screen.queryByText("등록된 강의자료가 없습니다.")).not.toBeInTheDocument();

    await act(async () => {
      materialList.resolve([]);
      await materialList.promise;
    });
  });

  it("does not add a delayed upload result to another course", async () => {
    const upload = deferred<typeof material>();
    apiMocks.listCourses.mockResolvedValue([course, secondCourse]);
    apiMocks.listCourseMaterials.mockResolvedValue([material]);
    apiMocks.uploadCourseMaterial.mockReturnValue(upload.promise);
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    const file = new File(["week two"], "week-2.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("강의자료 파일"), {
      target: { files: [file] }
    });
    fireEvent.click(screen.getByRole("button", { name: "업로드" }));
    const courseSelect = screen.getByRole("combobox", { name: "과목" });
    expect(courseSelect).toBeDisabled();

    fireEvent.change(courseSelect, { target: { value: "course-2" } });
    expect(courseSelect).toHaveValue("course-2");

    await act(async () => {
      upload.resolve({
        ...material,
        id: "material-2",
        originalFileName: "week-2.txt",
        processingStatus: "pending"
      });
      await upload.promise;
    });

    expect(screen.queryByText("week-2.txt")).not.toBeInTheDocument();
  });

  it("does not remove a row from another course after delayed deletion", async () => {
    const deletion = deferred<void>();
    apiMocks.listCourses.mockResolvedValue([course, secondCourse]);
    apiMocks.listCourseMaterials.mockResolvedValue([material]);
    apiMocks.deleteCourseMaterial.mockReturnValue(deletion.promise);
    render(<ProfessorMaterialsClient />);
    await screen.findByText("lecture.txt");
    fireEvent.click(screen.getByRole("button", { name: "lecture.txt 삭제" }));
    const courseSelect = screen.getByRole("combobox", { name: "과목" });
    expect(courseSelect).toBeDisabled();

    fireEvent.change(courseSelect, { target: { value: "course-2" } });
    expect(courseSelect).toHaveValue("course-2");
    await screen.findByText("lecture.txt");

    await act(async () => {
      deletion.resolve();
      await deletion.promise;
    });

    expect(screen.getByText("lecture.txt")).toBeInTheDocument();
  });

  it("renders processing and failed status details", async () => {
    apiMocks.listCourses.mockResolvedValue([course]);
    apiMocks.listCourseMaterials.mockResolvedValue([
      { ...material, id: "material-2", processingStatus: "processing" },
      {
        ...material,
        id: "material-3",
        processingStatus: "failed",
        processingError: "PDF에서 텍스트를 찾지 못했습니다."
      }
    ]);

    render(<ProfessorMaterialsClient />);

    expect(await screen.findByRole("button", { name: "lecture.txt 처리 중" })).toBeDisabled();
    expect(screen.getByText("처리 실패")).toBeInTheDocument();
    expect(
      screen.getByText("실패 원인: PDF에서 텍스트를 찾지 못했습니다.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "lecture.txt 재처리" })).toBeEnabled();
  });

  it("starts pending processing once and reloads materials and RAG status", async () => {
    const pending = { ...material, processingStatus: "pending" as const, chunkCount: 0 };
    const processing = deferred<CourseMaterial>();
    apiMocks.listCourses.mockResolvedValue([course]);
    apiMocks.listCourseMaterials
      .mockResolvedValueOnce([pending])
      .mockResolvedValueOnce([material]);
    apiMocks.getCourseRagStatus
      .mockResolvedValueOnce({ ...ragStatus, isSearchReady: false })
      .mockResolvedValueOnce(ragStatus);
    apiMocks.processCourseMaterial.mockReturnValue(processing.promise);
    render(<ProfessorMaterialsClient />);
    const processButton = await screen.findByRole("button", {
      name: "lecture.txt 처리 시작"
    });

    fireEvent.click(processButton);
    fireEvent.click(processButton);

    expect(apiMocks.processCourseMaterial).toHaveBeenCalledTimes(1);
    expect(processButton).toBeDisabled();
    expect(screen.getByText("처리 중...")).toBeInTheDocument();

    await act(async () => {
      processing.resolve(material);
      await processing.promise;
    });

    expect(await screen.findByText("이 과목은 검색 준비 완료")).toBeInTheDocument();
    expect(apiMocks.listCourseMaterials).toHaveBeenCalledTimes(2);
  });

  it("suppresses the empty state when material loading fails", async () => {
    apiMocks.listCourses.mockResolvedValue([course]);
    apiMocks.listCourseMaterials.mockRejectedValue(
      new ApiError(500, "강의자료를 조회할 수 없습니다.")
    );

    render(<ProfessorMaterialsClient />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "강의자료를 조회할 수 없습니다."
    );
    expect(screen.queryByText("등록된 강의자료가 없습니다.")).not.toBeInTheDocument();
  });
});
