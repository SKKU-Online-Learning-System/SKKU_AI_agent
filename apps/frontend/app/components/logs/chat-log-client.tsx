"use client";

import { useEffect, useState } from "react";
import { ApiError, getCourseKeywordCounts, listCourses } from "../../lib/api";
import type { CourseKeywordCounts, CourseSummary } from "../../lib/api";

export function ChatLogClient() {
  const [courses, setCourses] = useState<CourseSummary[] | null>(null);
  const [courseId, setCourseId] = useState("");
  const [counts, setCounts] = useState<CourseKeywordCounts | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    listCourses().then((items) => {
      if (!active) return;
      setCourses(items);
      setCourseId(items[0]?.id ?? "");
    }).catch(() => {
      if (active) setError("과목을 불러오지 못했습니다.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!courseId) return;
    let active = true;
    getCourseKeywordCounts(courseId).then((result) => {
      if (active) setCounts(result);
    }).catch((failure: unknown) => {
      if (active) {
        setError(failure instanceof ApiError && failure.status === 403
          ? "이 과목의 통계를 볼 수 없습니다."
          : "키워드 통계를 불러오지 못했습니다.");
      }
    });
    return () => { active = false; };
  }, [courseId]);

  const weeks = counts?.courseId === courseId ? counts.weeks : null;

  return (
    <section className="log-page">
      <header><h1>주차별 핵심 키워드</h1></header>
      <div className="log-filters">
        <label>
          과목
          <select
            value={courseId}
            disabled={!courses?.length}
            onChange={(event) => {
              setError("");
              setCounts(null);
              setCourseId(event.target.value);
            }}
          >
            {!courses?.length ? <option value="">선택할 과목이 없습니다.</option> : null}
            {courses?.map((course) => (
              <option key={course.id} value={course.id}>
                {course.title} · {course.term}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? <p className="admin-alert" role="alert">{error}</p> : null}
      <div className="course-table-wrap">
        <table className="course-table">
          <thead>
            <tr>
              <th scope="col">주차</th>
              <th scope="col">핵심 키워드</th>
              <th scope="col">질문 건수</th>
            </tr>
          </thead>
          <tbody>
            {weeks?.flatMap(({ week, keywords }) => keywords.map(({ keyword, questionCount }) => (
              <tr key={`${week}-${keyword}`}>
                <td>{week}주차</td><td>{keyword}</td><td>{questionCount.toLocaleString()}건</td>
              </tr>
            )))}
            {!error && !weeks && (!courses || courseId) ? (
              <tr><td colSpan={3}>불러오는 중입니다.</td></tr>
            ) : null}
            {!error && weeks?.length === 0 ? (
              <tr><td colSpan={3}>공개 기준을 충족한 키워드가 없습니다.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
