"use client";

import { useEffect, useState } from "react";
import { ApiError, listAdminCourses } from "../../lib/api";
import type { AdminCourse } from "../../lib/api";
import { CourseMaterialsClient } from "../../components/courses/course-materials-client";

export function AdminMaterialsClient() {
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    async function loadCourses() {
      try {
        const courseList = await listAdminCourses();
        if (!isCancelled) {
          setCourses(courseList);
          setSelectedCourseId(courseList[0]?.id ?? "");
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(error instanceof ApiError ? error.message : "과목을 불러오지 못했습니다.");
        }
      }
    }
    void loadCourses();
    return () => { isCancelled = true; };
  }, []);

  return (
    <section className="admin-materials-page">
      <header>
        <h1>전체 강의콘텐츠</h1>
        <p>과목을 선택해 교수자가 공개한 주차별 자료를 확인합니다.</p>
      </header>
      {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
      {!errorMessage ? (
        <label className="material-course-select">
          과목
          <select onChange={(event) => setSelectedCourseId(event.target.value)} value={selectedCourseId}>
            {courses.length === 0 ? <option value="">등록된 과목이 없습니다.</option> : null}
            {courses.map((course) => (
              <option key={course.id} value={course.id}>{course.name} · {course.semester}</option>
            ))}
          </select>
        </label>
      ) : null}
      {selectedCourseId ? <CourseMaterialsClient courseId={selectedCourseId} /> : null}
    </section>
  );
}
