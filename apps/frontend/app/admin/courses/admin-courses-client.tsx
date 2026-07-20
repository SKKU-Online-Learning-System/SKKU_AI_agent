"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  activateAdminCourse,
  ApiError,
  deactivateAdminCourse,
  listAdminCourses,
  listAdminUsers
} from "../../lib/api";
import type { AdminCourse, AdminCourseFilters, AdminUser } from "../../lib/api";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function statusLabel(isActive: boolean): string {
  return isActive ? "활성" : "비활성";
}

export function AdminCoursesClient() {
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [professors, setProfessors] = useState<AdminUser[]>([]);
  const [filters, setFilters] = useState<AdminCourseFilters>({ isActive: null });
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadCourses = useCallback(async (nextFilters: AdminCourseFilters = { isActive: null }) => {
    setErrorMessage(null);
    setIsLoading(true);
    try {
      const [courseList, professorList] = await Promise.all([
        listAdminCourses(nextFilters),
        listAdminUsers("professor")
      ]);
      setCourses(courseList);
      setProfessors(professorList);
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : "과목 목록을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    const loadTimer = window.setTimeout(() => {
      void loadCourses();
    }, 0);

    return () => window.clearTimeout(loadTimer);
  }, [loadCourses]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void loadCourses(filters);
  };

  const toggleActive = async (course: AdminCourse) => {
    setErrorMessage(null);
    try {
      const updated = course.isActive
        ? await deactivateAdminCourse(course.id)
        : await activateAdminCourse(course.id);
      setCourses((current) =>
        current.map((item) => (item.id === updated.id ? updated : item))
      );
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : "상태 변경에 실패했습니다.");
    }
  };

  return (
    <section className="admin-course-page">
      <header className="admin-page-header">
        <div>
          <h1>과목 관리</h1>
          <p>전체 과목을 조회하고 담당 교수자와 활성화 상태를 관리합니다.</p>
        </div>
        <Link className="primary-action" href="/admin/courses/new">
          새 과목
        </Link>
      </header>

      <form className="admin-filter-bar" onSubmit={handleSubmit}>
        <label>
          검색어
          <input
            onChange={(event) =>
              setFilters((current) => ({ ...current, keyword: event.target.value }))
            }
            placeholder="과목명, 학기, 설명"
            type="search"
            value={filters.keyword ?? ""}
          />
        </label>
        <label>
          학기
          <input
            onChange={(event) =>
              setFilters((current) => ({ ...current, semester: event.target.value }))
            }
            placeholder="2026-2"
            value={filters.semester ?? ""}
          />
        </label>
        <label>
          담당 교수
          <select
            onChange={(event) =>
              setFilters((current) => ({ ...current, professorId: event.target.value }))
            }
            value={filters.professorId ?? ""}
          >
            <option value="">전체</option>
            {professors.map((professor) => (
              <option key={professor.id} value={professor.id}>
                {professor.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          상태
          <select
            onChange={(event) => {
              const value = event.target.value;
              setFilters((current) => ({
                ...current,
                isActive: value === "" ? null : value === "true"
              }));
            }}
            value={filters.isActive === null ? "" : String(filters.isActive)}
          >
            <option value="">전체</option>
            <option value="true">활성</option>
            <option value="false">비활성</option>
          </select>
        </label>
        <button type="submit">필터 적용</button>
      </form>

      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}

      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>과목명</th>
              <th>학기</th>
              <th>담당 교수</th>
              <th>상태</th>
              <th>수강 접근</th>
              <th>생성일</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={7}>과목 목록을 불러오고 있습니다.</td>
              </tr>
            ) : courses.length === 0 ? (
              <tr>
                <td colSpan={7}>조건에 맞는 과목이 없습니다.</td>
              </tr>
            ) : (
              courses.map((course) => (
                <tr key={course.id}>
                  <td>
                    <strong>{course.name}</strong>
                    {course.description ? <span>{course.description}</span> : null}
                  </td>
                  <td>{course.semester}</td>
                  <td>{course.professorName}</td>
                  <td>
                    <span data-active={course.isActive}>{statusLabel(course.isActive)}</span>
                  </td>
                  <td>{course.studentAccessCount}명</td>
                  <td>{formatDate(course.createdAt)}</td>
                  <td>
                    <div className="table-actions">
                      <Link href={`/admin/courses/${course.id}`}>수정</Link>
                      <button type="button" onClick={() => void toggleActive(course)}>
                        {course.isActive ? "비활성화" : "활성화"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
