"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import type { WeakConceptQuiz as Quiz } from "../../lib/voice-api";
import { createWeakConceptQuiz, recordWeakConceptQuiz } from "../../lib/voice-api";

/**
 * An O/X quiz on one weak concept. The statements come from the course materials;
 * the finished quiz is recorded as one review, which moves the concept's mastery
 * and next review date like any other review.
 */
export function WeakConceptQuiz({
  courseId,
  memoryId,
  onClose,
  onRecorded
}: {
  courseId: string;
  memoryId: string;
  onClose: () => void;
  onRecorded: () => void;
}) {
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [choice, setChoice] = useState<boolean | null>(null);
  const [score, setScore] = useState(0);
  const [result, setResult] = useState<"recording" | "passed" | "failed" | "unsaved" | null>(
    null
  );
  const recordedRef = useRef(false);

  useEffect(() => {
    let isCancelled = false;
    createWeakConceptQuiz(courseId, memoryId)
      .then((created) => {
        if (!isCancelled) setQuiz(created);
      })
      .catch((reason: unknown) => {
        if (!isCancelled) {
          setError(reason instanceof ApiError ? reason.message : "퀴즈를 만들지 못했어요.");
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [courseId, memoryId]);

  const isFinished = quiz !== null && index >= quiz.items.length;

  useEffect(() => {
    if (!quiz || !isFinished || recordedRef.current) return;
    recordedRef.current = true;
    setResult("recording");
    recordWeakConceptQuiz(courseId, memoryId, score, quiz.items.length)
      .then((recorded) => {
        setResult(recorded.correct ? "passed" : "failed");
        onRecorded();
      })
      .catch(() => setResult("unsaved"));
  }, [courseId, isFinished, memoryId, onRecorded, quiz, score]);

  if (error) {
    return (
      <div className="weak-quiz" role="group" aria-label="O/X 퀴즈">
        <p className="admin-alert" role="alert">
          {error}
        </p>
        <button className="voice-secondary" onClick={onClose} type="button">
          닫기
        </button>
      </div>
    );
  }

  if (!quiz) {
    return (
      <div className="weak-quiz" role="group" aria-label="O/X 퀴즈">
        <p className="voice-empty">강의자료에서 문제를 만드는 중이에요.</p>
      </div>
    );
  }

  if (isFinished) {
    return (
      <div className="weak-quiz" role="group" aria-label="O/X 퀴즈">
        <p className="weak-quiz-score">
          {quiz.items.length}문제 중 {score}개 맞혔어요.
        </p>
        <p className="weak-quiz-note">
          {result === "passed" && "복습 성공으로 기록했어요. 다음 복습은 조금 더 뒤에 할게요."}
          {result === "failed" && "한 번 더 복습이 필요해요. 내일 다시 물어볼게요."}
          {result === "unsaved" && "결과를 저장하지 못했어요."}
          {result === "recording" && "결과를 기록하는 중이에요."}
        </p>
        <button className="voice-secondary" onClick={onClose} type="button">
          닫기
        </button>
      </div>
    );
  }

  const item = quiz.items[index];
  const answered = choice !== null;
  const isCorrect = choice === item.answer;

  const answer = (value: boolean) => {
    if (answered) return;
    setChoice(value);
    if (value === item.answer) setScore((current) => current + 1);
  };

  return (
    <div className="weak-quiz" role="group" aria-label="O/X 퀴즈">
      <p className="weak-quiz-progress">
        O/X 퀴즈 · {index + 1}/{quiz.items.length}
      </p>
      <p className="weak-quiz-statement">{item.statement}</p>
      <div className="weak-quiz-choices">
        {[true, false].map((value) => (
          <button
            aria-label={value ? "O, 맞다" : "X, 틀리다"}
            aria-pressed={choice === value}
            className="weak-quiz-choice"
            data-result={answered && value === item.answer ? "answer" : undefined}
            disabled={answered}
            key={String(value)}
            onClick={() => answer(value)}
            type="button"
          >
            {value ? "O" : "X"}
          </button>
        ))}
      </div>
      {answered ? (
        <div className="weak-quiz-feedback" data-correct={isCorrect} role="status">
          <strong>{isCorrect ? "정답이에요" : `아쉬워요. 정답은 ${item.answer ? "O" : "X"}예요`}</strong>
          <p>{item.explanation}</p>
          {item.source ? <small>근거: {item.source}</small> : null}
          <button
            className="voice-primary"
            onClick={() => {
              setChoice(null);
              setIndex((current) => current + 1);
            }}
            type="button"
          >
            {index + 1 < quiz.items.length ? "다음 문제" : "결과 보기"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
