"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, listAdminCourses, listCourses } from "../../lib/api";
import type { AdminCourse, CourseSummary } from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

type DashboardAudience = "admin" | "professor" | "student";

type DashboardCourse = {
  code: string;
  id: string;
  instructorName: string;
  meta?: string;
  status: "active" | "disabled" | "draft";
  term: string;
  title: string;
};

function adminCourseToDashboardCourse(course: AdminCourse): DashboardCourse {
  return {
    code: "관리 과목",
    id: course.id,
    instructorName: course.professorName,
    meta: `수강 접근 ${course.studentAccessCount}명`,
    status: course.isActive ? "active" : "disabled",
    term: course.semester,
    title: course.name
  };
}

function summaryToDashboardCourse(course: CourseSummary): DashboardCourse {
  return {
    code: course.code,
    id: course.id,
    instructorName: course.instructorName,
    status: course.agentStatus,
    term: course.term,
    title: course.title
  };
}

function courseBasePath(audience: DashboardAudience, courseId: string): string {
  return audience === "admin"
    ? `/admin/course/${courseId}`
    : `/${audience}/courses/${courseId}`;
}

function courseActions(audience: DashboardAudience, courseId: string) {
  const basePath = courseBasePath(audience, courseId);
  if (audience === "student") {
    return [
      { href: `${basePath}/materials`, icon: "material" as const, label: "강의자료" },
      { href: `${basePath}/chat`, icon: "agent" as const, label: "AI 질문" }
    ];
  }
  if (audience === "professor") {
    return [
      { href: `${basePath}/materials`, icon: "upload" as const, label: "강의자료 관리" }
    ];
  }
  return [
    { href: `${basePath}/settings`, icon: "course" as const, label: "과목 설정" },
    { href: `${basePath}/materials`, icon: "material" as const, label: "자료 현황" }
  ];
}

export function CourseDashboardClient({ audience }: { audience: DashboardAudience }) {
  const [courses, setCourses] = useState<DashboardCourse[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isCancelled = false;

    async function loadDashboardCourses() {
      try {
        const courseList =
          audience === "admin"
            ? (await listAdminCourses()).map(adminCourseToDashboardCourse)
            : (await listCourses()).map(summaryToDashboardCourse);
        if (!isCancelled) setCourses(courseList);
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError
              ? error.message
              : "대시보드 과목을 불러오지 못했습니다."
          );
        }
      } finally {
        if (!isCancelled) setIsLoading(false);
      }
    }

    void loadDashboardCourses();
    return () => {
      isCancelled = true;
    };
  }, [audience]);

  const emptyMessage =
    audience === "admin"
      ? "등록된 과목이 없습니다."
      : audience === "professor"
        ? "담당 과목이 없습니다."
        : "수강 중인 과목이 없습니다.";

  return (
    <section className="canvas-dashboard">
      <header className="canvas-dashboard-header">
        <div>
          <h1>대시보드</h1>
          <p>과목 카드를 선택해 과목별 학습 공간으로 이동합니다.</p>
        </div>
        <span>{isLoading ? "과목 불러오는 중" : `${courses.length}개 과목`}</span>
      </header>

      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}

      <div className="canvas-dashboard-layout">
        <div className="canvas-course-card-grid" aria-label="과목 카드">
          {isLoading
            ? Array.from({ length: 4 }, (_, index) => (
                <div className="canvas-course-card canvas-course-card--loading" key={index}>
                  <span />
                  <span />
                </div>
              ))
            : null}

          {!isLoading && !errorMessage && courses.length === 0 ? (
            <p className="canvas-dashboard-empty">{emptyMessage}</p>
          ) : null}

          {!isLoading
            ? courses.map((course, index) => {
                const basePath = courseBasePath(audience, course.id);
                return (
                  <article className="canvas-course-card" key={course.id}>
                    <Link className="canvas-course-card-primary" href={basePath}>
                      <span
                        className="canvas-course-card-visual"
                        data-color={index % 6}
                        data-status={course.status}
                      >
                        <UiIcon name="course" />
                      </span>
                      <span className="canvas-course-card-body">
                        <strong>{course.title}</strong>
                        <span>{course.code}</span>
                        <small>{course.instructorName}</small>
                        <small>{course.term}</small>
                        {course.meta ? <small>{course.meta}</small> : null}
                      </span>
                    </Link>
                    <nav aria-label={`${course.title} 바로가기`}>
                      {courseActions(audience, course.id).map((action) => (
                        <Link href={action.href} key={action.href} title={action.label}>
                          <UiIcon name={action.icon} />
                          <span className="sr-only">{action.label}</span>
                        </Link>
                      ))}
                    </nav>
                  </article>
                );
              })
            : null}
        </div>

        <aside className="canvas-dashboard-sidebar">
          <section>
            <h2>할 일</h2>
            <p>과목 카드를 열어 강의자료와 AI 코스 에이전트 상태를 확인하세요.</p>
          </section>
          <section>
            <h2>최근 피드백</h2>
            <p>현재 새로운 피드백이 없습니다.</p>
          </section>
        </aside>
      </div>
    </section>
  );
}
