"use client";

import { WeeklyMaterialList } from "./weekly-material-list";
import { useCourseMaterials } from "./use-course-materials";

export function CourseMaterialsClient({ courseId }: { courseId: string }) {
  const { errorMessage, isLoading, materials } = useCourseMaterials(courseId);

  return (
    <section className="material-manager">
      <header>
        <h1>강의콘텐츠</h1>
        <p>교수자가 공개한 자료를 주차별로 확인하고 내려받을 수 있습니다.</p>
      </header>
      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      {isLoading ? <p className="weekly-content-loading">강의자료를 불러오고 있습니다.</p> : null}
      {!isLoading && !errorMessage ? (
        <WeeklyMaterialList courseId={courseId} materials={materials} />
      ) : null}
    </section>
  );
}
