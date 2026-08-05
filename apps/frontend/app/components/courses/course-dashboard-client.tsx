"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  getMyStatistics,
  getProfessorStatistics,
  getServiceStatistics,
  listAdminCourses,
  listCourses
} from "../../lib/api";
import type {
  AdminCourse,
  CourseSummary,
  MyStatistics,
  ProfessorStatistics,
  ServiceStatistics
} from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

type DashboardAudience = "admin" | "professor" | "student";
type DashboardStatistics = ServiceStatistics | ProfessorStatistics | MyStatistics;

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

function StatisticsPanel({
  audience,
  statistics
}: {
  audience: DashboardAudience;
  statistics: DashboardStatistics;
}) {
  if (audience === "admin") {
    const data = statistics as ServiceStatistics;
    return (
      <section className="dashboard-statistics" aria-label="전체 서비스 통계">
        <div className="role-page-grid">
          <article><strong>전체 과목</strong><span>{data.totals.courseCount}개</span></article>
          <article><strong>전체 사용자</strong><span>{data.totals.userCount}명</span></article>
          <article><strong>전체 질문</strong><span>{data.totals.questionCount}건</span></article>
        </div>
        <div className="course-table-wrap">
          <table className="course-table">
            <thead><tr><th>과목</th><th>질문</th><th>사용자</th><th>업로드 자료</th></tr></thead>
            <tbody>{data.courses.map((course) => (
              <tr key={course.courseId}>
                <td>{course.courseName}</td><td>{course.questionCount}</td>
                <td>{course.userCount}</td><td>{course.materialCount}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <p className="dashboard-daily-summary">
          일자별 질문: {data.questionsByDate.length
            ? data.questionsByDate.map((item) => `${item.date} ${item.count}건`).join(" · ")
            : "아직 질문이 없습니다."}
        </p>
      </section>
    );
  }

  if (audience === "professor") {
    const data = statistics as ProfessorStatistics;
    return (
      <section className="dashboard-statistics" aria-label="담당 과목 통계">
        <div className="course-table-wrap">
          <table className="course-table">
            <thead><tr><th>담당 과목</th><th>업로드 자료</th><th>질문</th></tr></thead>
            <tbody>{data.courses.map((course) => (
              <tr key={course.courseId}>
                <td>{course.courseName}</td><td>{course.materialCount}</td><td>{course.questionCount}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <div className="dashboard-statistics-columns">
          <section><h2>최근 질문</h2>{data.recentQuestions.length
            ? <ul>{data.recentQuestions.map((item) => <li key={item.id}>{item.courseName} · {item.question}</li>)}</ul>
            : <p>최근 질문이 없습니다.</p>}</section>
          <section><h2>자주 나온 키워드</h2>{data.keywords.length
            ? <ul>{data.keywords.map((item) => <li key={item.keyword}>{item.keyword} ({item.count})</li>)}</ul>
            : <p>분석할 질문이 없습니다.</p>}</section>
        </div>
      </section>
    );
  }

  const data = statistics as MyStatistics;
  return (
    <section className="dashboard-statistics" aria-label="내 사용 통계">
      <div className="role-page-grid">
        <article><strong>내 질문</strong><span>{data.questionCount}건</span></article>
        <article><strong>내 대화</strong><span>{data.sessionCount}개</span></article>
      </div>
    </section>
  );
}

export function CourseDashboardClient({ audience }: { audience: DashboardAudience }) {
  const [courses, setCourses] = useState<DashboardCourse[]>([]);
  const [statistics, setStatistics] = useState<DashboardStatistics | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isCancelled = false;

    async function loadDashboardCourses() {
      try {
        const [courseResult, statisticsResult] = await Promise.all([
          audience === "admin" ? listAdminCourses() : listCourses(),
          audience === "admin"
            ? getServiceStatistics()
            : audience === "professor"
              ? getProfessorStatistics()
              : getMyStatistics()
        ]);
        if (!isCancelled) {
          setCourses(
            audience === "admin"
              ? (courseResult as AdminCourse[]).map(adminCourseToDashboardCourse)
              : (courseResult as CourseSummary[]).map(summaryToDashboardCourse)
          );
          setStatistics(statisticsResult);
        }
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
      {!isLoading && !errorMessage && statistics ? (
        <StatisticsPanel audience={audience} statistics={statistics} />
      ) : null}

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
