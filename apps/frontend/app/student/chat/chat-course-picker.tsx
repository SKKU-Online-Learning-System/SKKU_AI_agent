"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, listCourses } from "../../lib/api";
import type { CourseSummary } from "../../lib/api";

export function ChatCoursePicker() {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    async function loadCourses() {
      try {
        const courseList = await listCourses();
        if (!isCancelled) setCourses(courseList);
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "과목 목록을 불러오지 못했습니다."
          );
        }
      } finally {
        if (!isCancelled) setIsLoading(false);
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
        <h1>AI 질문</h1>
        <p>질문할 과목을 선택하면 해당 과목의 강의자료를 근거로 답변합니다.</p>
      </header>

      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}

      {isLoading ? (
        <p className="empty-state">과목 목록을 불러오고 있습니다.</p>
      ) : courses.length === 0 ? (
        <p className="empty-state">수강 중인 과목이 없습니다.</p>
      ) : (
        <div className="role-page-grid">
          {courses.map((course) => (
            <article key={course.id}>
              <strong>{course.title}</strong>
              <span>{course.instructorName}</span>
              <Link href={`/student/courses/${course.id}/chat`}>챗봇 시작</Link>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
