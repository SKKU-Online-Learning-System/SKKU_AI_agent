"use client";

import {
  ChangeEvent,
  FormEvent,
  useEffect,
  useRef,
  useState
} from "react";
import {
  ApiError,
  deleteCourseMaterial,
  listCourseMaterials,
  listCourses,
  uploadCourseMaterial
} from "../../lib/api";
import type { CourseMaterial, CourseSummary } from "../../lib/api";
import { WeeklyMaterialList } from "../../components/courses/weekly-material-list";

const allowedFileExtensions = new Set(["pdf", "pptx", "docx", "txt"]);
const maxFileSize = 20 * 1024 * 1024;
function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function fileExtension(fileName: string): string {
  return fileName.split(".").pop()?.toLowerCase() ?? "";
}

export function ProfessorMaterialsClient({ courseId }: { courseId?: string } = {}) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedWeek, setSelectedWeek] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deletingMaterialId, setDeletingMaterialId] = useState<string | null>(
    null
  );
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const selectedCourseIdRef = useRef<string>("");
  const isMutationActive = isSubmitting || deletingMaterialId !== null;

  const resetSelectedFile = () => {
    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  useEffect(() => {
    let isCancelled = false;

    async function loadAvailableCourses() {
      if (courseId) {
        selectedCourseIdRef.current = courseId;
        setSelectedCourseId(courseId);
        return;
      }
      try {
        const courseList = await listCourses();
        if (isCancelled) return;
        setCourses(courseList);
        const firstCourseId = courseList[0]?.id ?? "";
        selectedCourseIdRef.current = firstCourseId;
        setSelectedCourseId(firstCourseId);
        if (courseList.length === 0) {
          setIsLoading(false);
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            apiErrorMessage(error, "담당 과목을 불러오지 못했습니다.")
          );
          setIsLoading(false);
        }
      }
    }

    void loadAvailableCourses();

    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  useEffect(() => {
    if (!selectedCourseId) {
      return;
    }

    let isCancelled = false;

    async function loadMaterials() {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const materialList = await listCourseMaterials(selectedCourseId);
        if (!isCancelled) {
          setMaterials(materialList);
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            apiErrorMessage(error, "강의자료 목록을 불러오지 못했습니다.")
          );
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadMaterials();

    return () => {
      isCancelled = true;
    };
  }, [selectedCourseId]);

  const handleCourseChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const nextCourseId = event.target.value;
    selectedCourseIdRef.current = nextCourseId;
    setMaterials([]);
    resetSelectedFile();
    setErrorMessage(null);
    setIsLoading(Boolean(nextCourseId));
    setSelectedCourseId(nextCourseId);
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setErrorMessage(null);

    if (!file) {
      resetSelectedFile();
      return;
    }
    if (!allowedFileExtensions.has(fileExtension(file.name))) {
      resetSelectedFile();
      setErrorMessage("지원하지 않는 파일 형식입니다.");
      return;
    }
    if (file.size > maxFileSize) {
      resetSelectedFile();
      setErrorMessage("파일 크기는 20MB 이하여야 합니다.");
      return;
    }

    setSelectedFile(file);
  };

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedCourseId || !selectedFile) return;

    const operationCourseId = selectedCourseIdRef.current;
    const operationFile = selectedFile;
    setErrorMessage(null);
    setIsSubmitting(true);
    try {
      const uploadedMaterial = await uploadCourseMaterial(
        operationCourseId,
        operationFile,
        selectedWeek
      );
      if (selectedCourseIdRef.current !== operationCourseId) return;
      setMaterials((current) => [uploadedMaterial, ...current]);
      resetSelectedFile();
    } catch (error) {
      if (selectedCourseIdRef.current !== operationCourseId) return;
      setErrorMessage(apiErrorMessage(error, "강의자료 업로드에 실패했습니다."));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async (material: CourseMaterial) => {
    if (deletingMaterialId !== null || isSubmitting || isLoading) return;

    const operationCourseId = selectedCourseIdRef.current;
    setErrorMessage(null);
    setDeletingMaterialId(material.id);
    try {
      await deleteCourseMaterial(operationCourseId, material.id);
      if (selectedCourseIdRef.current !== operationCourseId) return;
      setMaterials((current) =>
        current.filter((item) => item.id !== material.id)
      );
    } catch (error) {
      if (selectedCourseIdRef.current !== operationCourseId) return;
      setErrorMessage(apiErrorMessage(error, "강의자료 삭제에 실패했습니다."));
    } finally {
      setDeletingMaterialId(null);
    }
  };

  return (
    <section className="material-manager">
      <header>
        <h1>강의자료 관리</h1>
        <p>주차를 선택해 업로드하면 학생 강의콘텐츠에 즉시 공개됩니다.</p>
      </header>

      {!courseId ? (
        <label className="material-course-select">
          과목
          <select
            disabled={courses.length === 0 || isMutationActive}
            onChange={handleCourseChange}
            value={selectedCourseId}
          >
            {courses.length === 0 ? (
              <option value="">담당 과목이 없습니다.</option>
            ) : (
              courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.code} {course.title}
                </option>
              ))
            )}
          </select>
        </label>
      ) : null}

      <form className="material-upload-form" onSubmit={handleUpload}>
        <label>
          주차
          <select
            disabled={!selectedCourseId || isLoading || isMutationActive}
            onChange={(event) => setSelectedWeek(Number(event.target.value))}
            value={selectedWeek}
          >
            {Array.from({ length: 16 }, (_, index) => index + 1).map((week) => (
              <option key={week} value={week}>{week}주차</option>
            ))}
          </select>
        </label>
        <label>
          강의자료 파일
          <input
            accept=".pdf,.pptx,.docx,.txt"
            disabled={!selectedCourseId || isLoading || isMutationActive}
            onChange={handleFileChange}
            ref={fileInputRef}
            type="file"
          />
        </label>
        <button
          disabled={
            !selectedCourseId ||
            !selectedFile ||
            isLoading ||
            isMutationActive
          }
          type="submit"
        >
          {isSubmitting ? "업로드 중..." : "업로드"}
        </button>
        <p>PDF, PPTX, DOCX, TXT 파일을 최대 20MB까지 업로드할 수 있습니다.</p>
      </form>

      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}

      {!errorMessage || materials.length > 0 ? (
        isLoading ? (
          <p className="weekly-content-loading">강의자료를 불러오고 있습니다.</p>
        ) : (
          <WeeklyMaterialList
            activeWeek={selectedWeek}
            courseId={selectedCourseId}
            deletingMaterialId={deletingMaterialId}
            isBusy={isLoading || isMutationActive}
            key={selectedWeek}
            materials={materials}
            onDelete={(material) => void handleDelete(material)}
          />
        )
      ) : null}
    </section>
  );
}
