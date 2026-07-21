"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, listCourseMaterials } from "../../lib/api";
import type { CourseMaterial } from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

type CourseHomeRole = "admin" | "professor" | "student";

const processingStatusLabels: Record<CourseMaterial["processingStatus"], string> = {
  completed: "처리 완료",
  failed: "처리 실패",
  pending: "처리 대기",
  processing: "처리 중"
};

function courseBasePath(role: CourseHomeRole, courseId: string): string {
  return role === "admin" ? `/admin/course/${courseId}` : `/${role}/courses/${courseId}`;
}

export function CourseHomeClient({ courseId, role }: { courseId: string; role: CourseHomeRole }) {
  const [materials, setMaterials] = useState<CourseMaterial[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const basePath = courseBasePath(role, courseId);

  useEffect(() => {
    let isCancelled = false;

    async function loadActivity() {
      try {
        const materialList = await listCourseMaterials(courseId);
        if (!isCancelled) setMaterials(materialList);
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "최근 활동을 불러오지 못했습니다."
          );
        }
      } finally {
        if (!isCancelled) setIsLoading(false);
      }
    }

    void loadActivity();
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  const completedCount = materials.filter(
    (material) => material.processingStatus === "completed"
  ).length;

  return (
    <section className="canvas-course-home">
      <header>
        <h1>과목 홈</h1>
        <p>최근 강의자료 활동과 AI 코스 에이전트 준비 상태를 확인합니다.</p>
      </header>
      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      <div className="canvas-course-home-layout">
        <div className="canvas-recent-activity">
          <h2>최근 활동</h2>
          {isLoading ? <p>최근 활동을 불러오고 있습니다.</p> : null}
          {!isLoading && materials.length === 0 ? (
            <p className="canvas-activity-empty">등록된 강의자료가 없습니다.</p>
          ) : null}
          {!isLoading && materials.length > 0 ? (
            <ul>
              {materials.slice(0, 5).map((material) => (
                <li key={material.id}>
                  <UiIcon name="material" />
                  <span>
                    <strong>{material.originalFileName}</strong>
                    <small>{processingStatusLabels[material.processingStatus]}</small>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <aside className="canvas-course-summary">
          <Link href={`${basePath}/materials`}>
            <UiIcon name="material" />
            강의자료 {materials.length}개
          </Link>
          <div>
            <span>AI 활용 가능 자료</span>
            <strong>{completedCount}개</strong>
          </div>
          {role === "student" ? (
            <Link href={`${basePath}/chat`}>
              <UiIcon name="agent" />
              AI 질문 시작
            </Link>
          ) : null}
          {role === "admin" ? (
            <Link href={`${basePath}/settings`}>
              <UiIcon name="course" />
              과목 설정
            </Link>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
