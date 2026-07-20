"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ApiError,
  createAdminCourse,
  getAdminCourse,
  listAdminUsers,
  updateAdminCourse
} from "../../lib/api";
import type { AdminCourse, AdminCoursePayload, AdminUser } from "../../lib/api";

type CourseFormClientProps = {
  courseId?: string;
  mode: "create" | "edit";
};

type CourseFormState = AdminCoursePayload;

const emptyForm: CourseFormState = {
  name: "",
  semester: "",
  description: "",
  professorId: "",
  isActive: true
};

export function CourseFormClient({ courseId, mode }: CourseFormClientProps) {
  const router = useRouter();
  const [form, setForm] = useState<CourseFormState>(emptyForm);
  const [course, setCourse] = useState<AdminCourse | null>(null);
  const [professors, setProfessors] = useState<AdminUser[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function loadFormData() {
      setErrorMessage(null);
      setIsLoading(true);
      try {
        const [professorList, loadedCourse] = await Promise.all([
          listAdminUsers("professor"),
          mode === "edit" && courseId ? getAdminCourse(courseId) : Promise.resolve(null)
        ]);

        if (!mounted) return;
        setProfessors(professorList);
        if (loadedCourse) {
          setCourse(loadedCourse);
          setForm({
            name: loadedCourse.name,
            semester: loadedCourse.semester,
            description: loadedCourse.description ?? "",
            professorId: loadedCourse.professorId,
            isActive: loadedCourse.isActive
          });
        } else {
          setForm({
            ...emptyForm,
            professorId: professorList[0]?.id ?? ""
          });
        }
      } catch (error) {
        if (!mounted) return;
        setErrorMessage(error instanceof ApiError ? error.message : "과목 정보를 불러오지 못했습니다.");
      } finally {
        if (mounted) setIsLoading(false);
      }
    }

    void loadFormData();
    return () => {
      mounted = false;
    };
  }, [courseId, mode]);

  const updateField = <Key extends keyof CourseFormState>(
    key: Key,
    value: CourseFormState[Key]
  ) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);
    setIsSubmitting(true);

    try {
      const payload = {
        ...form,
        description: form.description?.trim() ? form.description : null
      };
      if (mode === "create") {
        const created = await createAdminCourse(payload);
        router.replace(`/admin/courses/${created.id}`);
      } else if (courseId) {
        const updated = await updateAdminCourse(courseId, payload);
        setCourse(updated);
        setSuccessMessage("과목 정보가 저장되었습니다.");
      }
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : "과목 저장에 실패했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const title = mode === "create" ? "과목 생성" : "과목 수정";

  return (
    <section className="admin-course-page">
      <header className="admin-page-header">
        <div>
          <h1>{title}</h1>
          <p>
            {mode === "create"
              ? "새 과목과 담당 교수자를 지정합니다."
              : `${course?.name ?? "선택한 과목"} 정보를 수정합니다.`}
          </p>
        </div>
        <Link className="secondary-action" href="/admin/courses">
          목록으로
        </Link>
      </header>

      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      {successMessage ? <p className="admin-success" role="status">{successMessage}</p> : null}

      <form className="admin-course-form" onSubmit={handleSubmit}>
        <label>
          과목명
          <input
            disabled={isLoading}
            onChange={(event) => updateField("name", event.target.value)}
            required
            value={form.name}
          />
        </label>
        <label>
          학기
          <input
            disabled={isLoading}
            onChange={(event) => updateField("semester", event.target.value)}
            placeholder="2026-2"
            required
            value={form.semester}
          />
        </label>
        <label>
          담당 교수자
          <select
            disabled={isLoading || professors.length === 0}
            onChange={(event) => updateField("professorId", event.target.value)}
            required
            value={form.professorId}
          >
            <option value="">교수자를 선택하세요</option>
            {professors.map((professor) => (
              <option key={professor.id} value={professor.id}>
                {professor.name} ({professor.email})
              </option>
            ))}
          </select>
        </label>
        <label>
          설명
          <textarea
            disabled={isLoading}
            onChange={(event) => updateField("description", event.target.value)}
            rows={5}
            value={form.description ?? ""}
          />
        </label>
        <label className="checkbox-field">
          <input
            checked={form.isActive}
            disabled={isLoading}
            onChange={(event) => updateField("isActive", event.target.checked)}
            type="checkbox"
          />
          활성 과목
        </label>
        <div className="form-actions">
          <button disabled={isLoading || isSubmitting || !form.professorId} type="submit">
            {isSubmitting ? "저장 중" : "저장"}
          </button>
          <Link href="/admin/courses">취소</Link>
        </div>
      </form>
    </section>
  );
}
