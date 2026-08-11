"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getAdminCourse, listCourses } from "../../lib/api";
import { roleLabels } from "../../lib/auth";
import { useAuth } from "../auth/auth-provider";
import { CourseAgentSymbol } from "../ui/course-agent-symbol";
import type { IconName } from "../ui/ui-icon";
import { UiIcon } from "../ui/ui-icon";

type CourseWorkspaceRole = "admin" | "professor" | "student";

type WorkspaceCourse = {
  code: string;
  term: string;
  title: string;
};

type CourseNavigationItem = {
  /** null renders the menu entry greyed out, as i-Campus does for unused tools. */
  href: string | null;
  icon: IconName | "agent-symbol";
  label: string;
};

function basePath(role: CourseWorkspaceRole, courseId: string): string {
  return role === "admin" ? `/admin/course/${courseId}` : `/${role}/courses/${courseId}`;
}

/**
 * The i-Campus course menu, in the order canvas.skku.edu renders it. Tools this
 * MVP implements are links; the rest stay visible but inactive so the course
 * shell matches the real LMS.
 */
function navigationItems(role: CourseWorkspaceRole, courseId: string): CourseNavigationItem[] {
  const coursePath = basePath(role, courseId);
  // Students ask through COURSE AGENT, so they get no extra tool here.
  const roleSpecific: CourseNavigationItem[] =
    role === "professor"
      ? [{ href: `${coursePath}/rag-debug`, icon: "source", label: "RAG 디버그" }]
      : role === "admin"
        ? [{ href: `${coursePath}/settings`, icon: "course", label: "과목 설정" }]
        : [];

  return [
    { href: coursePath, icon: "home", label: "홈" },
    { href: null, icon: "posts", label: "수업 계획서" },
    { href: null, icon: "message", label: "공지" },
    { href: null, icon: "message", label: "게시판" },
    { href: `${coursePath}/materials`, icon: "content", label: "강의콘텐츠" },
    { href: null, icon: "check", label: "과제 및 평가" },
    { href: null, icon: "question", label: "시험 및 설문" },
    { href: null, icon: "attendance", label: "출결현황" },
    { href: null, icon: "chart", label: "학습 활동 현황" },
    { href: null, icon: "grade", label: "성적" },
    ...roleSpecific,
    { href: `${coursePath}/course-agent`, icon: "agent-symbol", label: "COURSE AGENT" }
  ];
}

export function CourseWorkspaceClient({
  children,
  courseId,
  role
}: {
  children: React.ReactNode;
  courseId: string;
  role: CourseWorkspaceRole;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout, user } = useAuth();
  const [course, setCourse] = useState<WorkspaceCourse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isNavigationOpen, setIsNavigationOpen] = useState(true);
  const items = navigationItems(role, courseId);
  const activeItem = items.find((item) => item.href === pathname) ?? items[0];

  useEffect(() => {
    let isCancelled = false;

    async function loadCourse() {
      try {
        if (role === "admin") {
          const adminCourse = await getAdminCourse(courseId);
          if (!isCancelled) {
            setCourse({
              code: "관리 과목",
              term: adminCourse.semester,
              title: adminCourse.name
            });
          }
          return;
        }

        const courseList = await listCourses();
        const selectedCourse = courseList.find((item) => item.id === courseId);
        if (!selectedCourse) throw new ApiError(404, "과목을 찾을 수 없습니다.");
        if (!isCancelled) {
          setCourse({
            code: selectedCourse.code,
            term: selectedCourse.term,
            title: selectedCourse.title
          });
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "과목 정보를 불러오지 못했습니다."
          );
        }
      }
    }

    void loadCourse();
    return () => {
      isCancelled = true;
    };
  }, [courseId, role]);

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  return (
    <section className="icampus-course-workspace">
      <header className="icampus-app-topbar">
        <button
          aria-controls="icampus-course-navigation"
          aria-expanded={isNavigationOpen}
          aria-label={isNavigationOpen ? "과목 메뉴 접기" : "과목 메뉴 열기"}
          className="icampus-menu-toggle"
          onClick={() => setIsNavigationOpen((isOpen) => !isOpen)}
          type="button"
        >
          <span aria-hidden="true">☰</span>
        </button>
        <strong>
          <b>{course?.title ?? "과목을 불러오는 중입니다."}</b>
          {activeItem.label !== "홈" ? <> &nbsp;›&nbsp; {activeItem.label}</> : null}
        </strong>
        <div className="icampus-user-menu">
          {user ? (
            <span>
              {user.name} {roleLabels[user.role]}
            </span>
          ) : null}
          <button type="button" onClick={handleLogout}>
            로그아웃
          </button>
        </div>
      </header>
      <div className="icampus-course-layout" data-nav-open={isNavigationOpen}>
        <aside
          aria-label="과목 메뉴 영역"
          className="icampus-context-nav icampus-course-nav"
          data-open={isNavigationOpen}
          id="icampus-course-navigation"
        >
          <strong>
            {course?.term ?? "학기 정보"}
            {course ? ` · ${course.code}` : ""}
          </strong>
          <nav aria-label="과목 메뉴">
            {items.map((item) =>
              item.href ? (
                <Link
                  aria-current={item.href === pathname ? "page" : undefined}
                  href={item.href}
                  key={item.label}
                >
                  {item.icon === "agent-symbol" ? (
                    <CourseAgentSymbol size={16} state="presence" />
                  ) : (
                    <UiIcon name={item.icon} />
                  )}
                  <span>{item.label}</span>
                </Link>
              ) : (
                <span key={item.label} title="이 MVP에서는 제공하지 않는 메뉴입니다.">
                  <UiIcon name={item.icon as IconName} />
                  <span>{item.label}</span>
                </span>
              )
            )}
          </nav>
        </aside>
        <main className="icampus-course-main">
          {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : children}
        </main>
      </div>
    </section>
  );
}
