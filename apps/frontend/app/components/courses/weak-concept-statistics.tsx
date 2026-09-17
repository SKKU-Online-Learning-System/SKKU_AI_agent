"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  getCourseWeakConceptStatistics,
  getWeakConceptStatistics
} from "../../lib/api";
import type {
  CourseWeakConceptStatistics,
  WeakConceptStatistics,
  WeakConceptStatus,
  WeakConceptStatusCounts
} from "../../lib/api";

const STATUS_LABELS: Record<WeakConceptStatus, string> = {
  new: "신규",
  practicing: "학습 중",
  mastered: "학습 완료"
};

function formatDateTime(value: string | null): string {
  if (!value) return "기록 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "기록 없음";
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

function statusSummary(counts: WeakConceptStatusCounts): string {
  return `${STATUS_LABELS.new} ${counts.new} · ${STATUS_LABELS.practicing} ${counts.practicing} · ${STATUS_LABELS.mastered} ${counts.mastered}`;
}

function MasteryBar({ label, percent }: { label: string; percent: number }) {
  return (
    <div className="weak-stats-mastery">
      <div
        aria-label={`${label} 평균 이해도`}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={percent}
        className="weak-stats-mastery-track"
        role="progressbar"
      >
        <span style={{ width: `${percent}%` }} />
      </div>
      <small>{percent}%</small>
    </div>
  );
}

function CourseDetail({ detail }: { detail: CourseWeakConceptStatistics }) {
  if (detail.recordCount === 0) {
    return <p className="weak-stats-empty">이 과목에서 아직 포착된 취약 개념이 없습니다.</p>;
  }

  return (
    <div className="weak-stats-detail">
      <section aria-labelledby={`weak-topics-${detail.courseId}`}>
        <h3 id={`weak-topics-${detail.courseId}`}>주제별</h3>
        <div className="course-table-wrap">
          <table className="course-table">
            <thead>
              <tr>
                <th>주제</th>
                <th>학생</th>
                <th>세부 개념</th>
                <th>누적 오답</th>
                <th>평균 이해도</th>
              </tr>
            </thead>
            <tbody>
              {detail.topics.map((topic) => (
                <tr key={topic.topic}>
                  <td>{topic.topic}</td>
                  <td>{topic.studentCount}명</td>
                  <td>{topic.conceptCount}개</td>
                  <td>{topic.failureCount}회</td>
                  <td>
                    <MasteryBar label={topic.topic} percent={topic.averageMastery} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby={`weak-concepts-${detail.courseId}`}>
        <h3 id={`weak-concepts-${detail.courseId}`}>개념별</h3>
        <div className="course-table-wrap">
          <table className="course-table">
            <thead>
              <tr>
                <th>취약 개념</th>
                <th>학생</th>
                <th>상태</th>
                <th>오답 / 정답</th>
                <th>평균 이해도</th>
                <th>최근 활동</th>
              </tr>
            </thead>
            <tbody>
              {detail.concepts.map((row) => (
                <tr key={row.concept}>
                  <td>
                    {row.concept}
                    {row.sampleNotes.length ? (
                      <small className="weak-stats-notes">{row.sampleNotes.join(" / ")}</small>
                    ) : null}
                  </td>
                  <td>{row.studentCount}명</td>
                  <td>{statusSummary(row.statusCounts)}</td>
                  <td>
                    {row.failureCount}회 / {row.successCount}회
                  </td>
                  <td>
                    <MasteryBar label={row.concept} percent={row.averageMastery} />
                  </td>
                  <td>{formatDateTime(row.lastSeenAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby={`weak-students-${detail.courseId}`}>
        <h3 id={`weak-students-${detail.courseId}`}>학생별</h3>
        <div className="course-table-wrap">
          <table className="course-table">
            <thead>
              <tr>
                <th>학생</th>
                <th>취약 개념</th>
                <th>상태</th>
                <th>평균 이해도</th>
                <th>복습 예정</th>
                <th>가장 약한 개념</th>
                <th>최근 활동</th>
              </tr>
            </thead>
            <tbody>
              {detail.students.map((row) => (
                <tr key={row.studentId}>
                  <td>{row.label}</td>
                  <td>{row.conceptCount}개</td>
                  <td>{statusSummary(row.statusCounts)}</td>
                  <td>
                    <MasteryBar label={row.label} percent={row.averageMastery} />
                  </td>
                  <td>{row.dueReviewCount}건</td>
                  <td>{row.weakestConcepts.join(", ")}</td>
                  <td>{formatDateTime(row.lastSeenAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby={`weak-recent-${detail.courseId}`}>
        <h3 id={`weak-recent-${detail.courseId}`}>최근 포착</h3>
        <ul>
          {detail.recentCaptures.map((capture, index) => (
            <li key={`${capture.concept}-${capture.studentLabel}-${index}`}>
              <strong>{capture.concept}</strong> · {capture.studentLabel} ·{" "}
              {STATUS_LABELS[capture.status]} · 이해도 {capture.masteryPercent}% ·{" "}
              {formatDateTime(capture.lastSeenAt)}
              {capture.difficultyNote ? <span>{capture.difficultyNote}</span> : null}
            </li>
          ))}
        </ul>
      </section>

      <p className="dashboard-daily-summary">
        일자별 포착:{" "}
        {detail.savedByDate.length
          ? detail.savedByDate.map((item) => `${item.date} ${item.count}건`).join(" · ")
          : "기록이 없습니다."}
      </p>
    </div>
  );
}

/** The last course detail that arrived, kept with the course it answers for. */
type DetailState = {
  courseId: string;
  detail?: CourseWeakConceptStatistics;
  error?: string;
};

export function WeakConceptStatisticsPanel({ audience }: { audience: "admin" | "professor" }) {
  const [overview, setOverview] = useState<WeakConceptStatistics | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [isOverviewLoading, setIsOverviewLoading] = useState(true);
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [detailState, setDetailState] = useState<DetailState | null>(null);

  useEffect(() => {
    let isCancelled = false;

    getWeakConceptStatistics()
      .then((result) => {
        if (isCancelled) return;
        setOverview(result);
        // Open the first course that has anything to show, so the detail is
        // one glance away instead of one more click.
        const first = result.courses.find((course) => course.recordCount > 0);
        setSelectedCourseId(first ? first.courseId : null);
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setOverviewError(
          error instanceof ApiError ? error.message : "취약 개념 통계를 불러오지 못했습니다."
        );
      })
      .finally(() => {
        if (!isCancelled) setIsOverviewLoading(false);
      });

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedCourseId) return;
    let isCancelled = false;

    getCourseWeakConceptStatistics(selectedCourseId)
      .then((result) => {
        if (!isCancelled) setDetailState({ courseId: selectedCourseId, detail: result });
      })
      .catch((error: unknown) => {
        if (isCancelled) return;
        setDetailState({
          courseId: selectedCourseId,
          error:
            error instanceof ApiError ? error.message : "과목별 취약 개념을 불러오지 못했습니다."
        });
      });

    return () => {
      isCancelled = true;
    };
  }, [selectedCourseId]);

  const selectedCourse = overview?.courses.find((course) => course.courseId === selectedCourseId);
  // A detail for another course is stale, not wrong: it simply is not shown.
  const selectedDetail = detailState?.courseId === selectedCourseId ? detailState : null;
  const isDetailLoading = Boolean(selectedCourseId) && selectedDetail === null;

  return (
    <section className="dashboard-statistics weak-stats" aria-label="취약 개념 통계">
      <header className="weak-stats-header">
        <h2>취약 개념 현황</h2>
        <p>
          {audience === "admin" ? "전체 과목" : "담당 과목"}에서 COURSE AGENT가 학생과의 대화 중
          포착한 취약 개념입니다. 학생이 헷갈리거나 틀린 개념만 기록되며, 복습 결과에 따라 상태가
          바뀝니다.
        </p>
      </header>

      {overviewError ? (
        <p className="admin-alert" role="alert">
          {overviewError}
        </p>
      ) : null}
      {isOverviewLoading ? (
        <p className="weak-stats-empty">취약 개념 통계를 불러오는 중입니다.</p>
      ) : null}

      {overview ? (
        <>
          <div className="role-page-grid">
            <article>
              <strong>취약 개념 기록</strong>
              <span>{overview.totals.recordCount}건</span>
            </article>
            <article>
              <strong>학생</strong>
              <span>{overview.totals.studentCount}명</span>
            </article>
            <article>
              <strong>평균 이해도</strong>
              <span>{overview.totals.averageMastery}%</span>
            </article>
            <article>
              <strong>복습 예정</strong>
              <span>{overview.totals.dueReviewCount}건</span>
            </article>
          </div>
          <p className="weak-stats-status">상태 분포: {statusSummary(overview.totals.statusCounts)}</p>

          {overview.courses.length ? (
            <div className="course-table-wrap">
              <table className="course-table">
                <thead>
                  <tr>
                    <th>과목</th>
                    <th>학생</th>
                    <th>개념</th>
                    <th>기록</th>
                    <th>상태</th>
                    <th>평균 이해도</th>
                    <th>복습 예정</th>
                    <th>최근 활동</th>
                    <th>
                      <span className="sr-only">상세 보기</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {overview.courses.map((course) => (
                    <tr data-selected={course.courseId === selectedCourseId} key={course.courseId}>
                      <td>{course.courseName}</td>
                      <td>{course.studentCount}명</td>
                      <td>{course.conceptCount}개</td>
                      <td>{course.recordCount}건</td>
                      <td>{statusSummary(course.statusCounts)}</td>
                      <td>{course.averageMastery}%</td>
                      <td>{course.dueReviewCount}건</td>
                      <td>{formatDateTime(course.lastActivityAt)}</td>
                      <td>
                        <button
                          aria-pressed={course.courseId === selectedCourseId}
                          className="voice-secondary"
                          disabled={course.recordCount === 0}
                          onClick={() => setSelectedCourseId(course.courseId)}
                          type="button"
                        >
                          {course.courseName} 자세히
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="weak-stats-empty">표시할 과목이 없습니다.</p>
          )}

          {selectedCourseId ? (
            <section
              aria-labelledby="weak-stats-course-title"
              aria-live="polite"
              className="weak-stats-course"
            >
              <h3 id="weak-stats-course-title">{selectedCourse?.courseName ?? "과목"} 상세</h3>
              {selectedDetail?.error ? (
                <p className="admin-alert" role="alert">
                  {selectedDetail.error}
                </p>
              ) : null}
              {isDetailLoading ? (
                <p className="weak-stats-empty">과목별 취약 개념을 불러오는 중입니다.</p>
              ) : null}
              {selectedDetail?.detail ? <CourseDetail detail={selectedDetail.detail} /> : null}
            </section>
          ) : overview.courses.length ? (
            <p className="weak-stats-empty">아직 포착된 취약 개념이 없습니다.</p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
