"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getAdminCourse, listCourses } from "../../lib/api";
import type { IconName } from "../ui/ui-icon";
import { UiIcon } from "../ui/ui-icon";

type CourseWorkspaceRole = "admin" | "professor" | "student";

type WorkspaceCourse = {
  code: string;
  term: string;
  title: string;
};

type CourseNavigationItem = {
  href: string;
  icon: IconName;
  label: string;
};

function basePath(role: CourseWorkspaceRole, courseId: string): string {
  return role === "admin" ? `/admin/course/${courseId}` : `/${role}/courses/${courseId}`;
}

function navigationItems(role: CourseWorkspaceRole, courseId: string): CourseNavigationItem[] {
  const coursePath = basePath(role, courseId);
  if (role === "student") {
    return [
      { href: coursePath, icon: "home", label: "홈" },
      { href: `${coursePath}/materials`, icon: "material", label: "강의콘텐츠" },
      { href: `${coursePath}/chat`, icon: "agent", label: "AI 질문" }
    ];
  }
  if (role === "professor") {
    return [
      { href: coursePath, icon: "home", label: "홈" },
      { href: `${coursePath}/materials`, icon: "upload", label: "강의콘텐츠" }
    ];
  }
  return [
    { href: coursePath, icon: "home", label: "홈" },
    { href: `${coursePath}/settings`, icon: "course", label: "과목 설정" },
    { href: `${coursePath}/materials`, icon: "material", label: "강의콘텐츠" }
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

  return (
    <section className="canvas-course-workspace" data-nav-open={isNavigationOpen}>
      <header className="canvas-course-header">
        <button
          aria-controls="canvas-course-navigation"
          aria-expanded={isNavigationOpen}
          aria-label={isNavigationOpen ? "과목 탐색 메뉴 숨기기" : "과목 탐색 메뉴 보이기"}
          onClick={() => setIsNavigationOpen((isOpen) => !isOpen)}
          type="button"
        >
          ☰
        </button>
        <div>
          <strong>{course?.title ?? "과목을 불러오는 중입니다."}</strong>
          {activeItem.label !== "홈" ? <span>› {activeItem.label}</span> : null}
        </div>
      </header>
      <div className="canvas-course-layout">
        <aside
          aria-label="과목 탐색 메뉴 영역"
          className="canvas-course-navigation"
          id="canvas-course-navigation"
        >
          <div>
            <span>{course?.term ?? "학기 정보"}</span>
            {course ? <small>{course.code}</small> : null}
          </div>
          <nav aria-label="과목 탐색 메뉴">
            {items.map((item) => (
              <Link
                aria-current={item.href === pathname ? "page" : undefined}
                href={item.href}
                key={item.href}
              >
                <UiIcon name={item.icon} />
                {item.label}
              </Link>
            ))}
          </nav>
        </aside>
        <main className="canvas-course-main">
          {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : children}
        </main>
      </div>
    </section>
  );
}
