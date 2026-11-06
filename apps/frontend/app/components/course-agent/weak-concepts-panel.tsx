"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { listWeakConcepts } from "../../lib/voice-api";
import type { WeakConcept } from "../../lib/voice-api";
import { WeakConceptQuiz } from "./weak-concept-quiz";

const WEAK_CONCEPT_STATUS_LABELS: Record<WeakConcept["status"], string> = {
  new: "신규",
  practicing: "학습 중",
  mastered: "학습 완료"
};

/**
 * The learner's weak concepts for one course, with the O/X quiz on each. Loads
 * itself, so it can sit on the COURSE AGENT page and in the study page's own
 * 취약 개념 tab alike.
 */
export function WeakConceptsPanel({
  courseId,
  variant = "card"
}: {
  courseId: string;
  /** "card" keeps the i-Campus card frame; "panel" is the study page's bare list. */
  variant?: "card" | "panel";
}) {
  const [weakConcepts, setWeakConcepts] = useState<WeakConcept[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [quizMemoryId, setQuizMemoryId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const result = await listWeakConcepts(courseId);
      setWeakConcepts(result.concepts);
    } catch (error) {
      setErrorMessage(error instanceof ApiError ? error.message : "취약 개념을 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    let isCancelled = false;
    listWeakConcepts(courseId)
      .then((result) => {
        if (!isCancelled) setWeakConcepts(result.concepts);
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "취약 개념을 불러오지 못했습니다."
          );
        }
      })
      .finally(() => {
        if (!isCancelled) setIsLoading(false);
      });
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  const refreshButton = (
    <button className="voice-secondary" disabled={isLoading} onClick={() => void load()} type="button">
      {isLoading ? "불러오는 중" : "새로고침"}
    </button>
  );

  const body = (
    <>
      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}
      {!errorMessage && isLoading && weakConcepts.length === 0 ? (
        <p className="voice-empty">취약 개념을 불러오는 중입니다.</p>
      ) : null}
      {!errorMessage && !isLoading && weakConcepts.length === 0 ? (
        <p className="voice-empty">아직 저장된 취약 개념이 없습니다.</p>
      ) : null}
      {weakConcepts.length > 0 ? (
        <div className="weak-concept-list">
          {weakConcepts.map((item) => (
            <article className="weak-concept-item" key={item.memory_id}>
              <div className="weak-concept-head">
                <h3>{item.concept}</h3>
                <span className="icampus-term-badge">{WEAK_CONCEPT_STATUS_LABELS[item.status]}</span>
              </div>
              <p>{item.difficulty_note}</p>
              <div className="weak-mastery-row">
                <div
                  aria-label={`${item.concept} 이해도`}
                  aria-valuemax={100}
                  aria-valuemin={0}
                  aria-valuenow={item.mastery_percent}
                  className="weak-mastery-track"
                  role="progressbar"
                >
                  <span style={{ width: `${item.mastery_percent}%` }} />
                </div>
                <strong>{item.mastery_percent}%</strong>
              </div>
              {quizMemoryId === item.memory_id ? (
                <WeakConceptQuiz
                  courseId={courseId}
                  memoryId={item.memory_id}
                  onClose={() => setQuizMemoryId(null)}
                  onRecorded={load}
                />
              ) : (
                <button
                  className="voice-secondary weak-quiz-start"
                  onClick={() => setQuizMemoryId(item.memory_id)}
                  type="button"
                >
                  O/X 퀴즈 풀기
                </button>
              )}
            </article>
          ))}
        </div>
      ) : null}
    </>
  );

  if (variant === "panel") {
    return (
      <div className="study-weak">
        <div className="study-weak-toolbar">
          <small>COURSE AGENT가 대화에서 발견한 이 과목의 학습 포인트</small>
          {refreshButton}
        </div>
        {body}
      </div>
    );
  }

  return (
    <section aria-labelledby="weak-concepts-title" className="icampus-card weak-concepts-card">
      <div className="icampus-card-head">
        <div>
          <h2 id="weak-concepts-title">내 취약 개념</h2>
          <small>COURSE AGENT가 대화에서 발견한 현재 과목의 학습 포인트입니다.</small>
        </div>
        {refreshButton}
      </div>
      <div className="icampus-card-body">{body}</div>
    </section>
  );
}
