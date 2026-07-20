"use client";

import { useEffect, useState } from "react";
import { ApiError, listCourses } from "../../lib/api";
import type { CourseSummary } from "../../lib/api";

type CourseListClientProps = {
  audience: "professor" | "student";
};

const agentStatusLabels: Record<CourseSummary["agentStatus"], string> = {
  draft: "초안",
  active: "활성",
  disabled: "비활성"
};

export function CourseListClient({ audience }: CourseListClientProps) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const title = audience === "professor" ? "담당 과목" : "내 과목";
  const description =
    audience === "professor"
      ? "담당 교수자로 등록된 과목과 에이전트 상태를 확인합니다."
      : "수강할 수 있는 활성 과목과 에이전트 상태를 확인합니다.";
  const emptyMessage =
    audience === "professor"
      ? "담당 과목이 없습니다."
      : "수강 중인 과목이 없습니다.";

  useEffect(() => {
    let isCancelled = false;

    async function loadCourses() {
      try {
        const courseList = await listCourses();
        if (!isCancelled) {
          setCourses(courseList);
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError
              ? error.message
              : "과목 목록을 불러오지 못했습니다."
          );
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadCourses();

    return () => {
      isCancelled = true;
    };
  }, []);

  return (
    <section className="course-list-page">
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>

      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}

      <div className="course-table-wrap">
        <table className="course-table">
          <thead>
            <tr>
              <th scope="col">과목명</th>
              <th scope="col">과목 코드</th>
              <th scope="col">학기</th>
              <th scope="col">에이전트 상태</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={4}>과목 목록을 불러오고 있습니다.</td>
              </tr>
            ) : courses.length === 0 ? (
              <tr>
                <td className="empty-state" colSpan={4}>
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              courses.map((course) => (
                <tr key={course.id}>
                  <td>
                    <strong>{course.title}</strong>
                  </td>
                  <td>{course.code}</td>
                  <td>{course.term}</td>
                  <td>
                    <span
                      className="material-status"
                      data-status={course.agentStatus}
                    >
                      {agentStatusLabels[course.agentStatus]}
                    </span>
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
