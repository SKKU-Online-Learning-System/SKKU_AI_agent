"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, getMaterialPageNote } from "../../lib/api";
import type { PageNote } from "../../lib/api";
import { MathText } from "../course-agent/math-text";

type NoteState =
  | { status: "loading" }
  | { status: "ready"; note: PageNote }
  | { status: "error"; message: string };

/** The AI 해설 for the page on screen: written once per page, cached per material. */
export function PageNotePane({
  courseId,
  materialId,
  onAsk,
  onNoted,
  page,
  week
}: {
  courseId: string;
  materialId: string;
  onAsk?: () => void;
  /** Called once the page's note exists, so the thumbnail strip can mark it. */
  onNoted?: (page: number) => void;
  page: number;
  week: number;
}) {
  const cache = useRef(new Map<string, PageNote>());
  const [state, setState] = useState<NoteState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  // Seconds since this page's note was requested, so a 20-second wait reads as
  // progress rather than a hang.
  useEffect(() => {
    if (state.status !== "loading") return;
    const startedAt = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [state.status, materialId, page, attempt]);

  useEffect(() => {
    const key = `${materialId}:${page}`;
    const cached = cache.current.get(key);
    if (cached) {
      setState({ status: "ready", note: cached });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    setElapsed(0);
    getMaterialPageNote(courseId, materialId, page).then(
      (note) => {
        cache.current.set(key, note);
        if (!cancelled) {
          setState({ status: "ready", note });
          onNoted?.(page);
        }
      },
      (error) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof ApiError ? error.message : "해설을 불러오지 못했습니다."
          });
        }
      }
    );
    return () => {
      cancelled = true;
    };
    // onNoted is a stable callback from the study page; the note is keyed by page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt, courseId, materialId, page]);

  return (
    <aside aria-label="AI 교안 해설" className="study-note">
      <div className="study-note-kicker">
        {week}주차 · p.{page}
      </div>
      {state.status === "loading" ? (
        <div className="study-note-loading" role="status">
          <div className="study-note-progress">
            <span aria-hidden="true" className="study-note-spinner" />
            <span className="study-note-shimmer">
              {elapsed < 2 ? "해설을 불러오는 중…" : "AI가 이 페이지를 읽고 해설을 쓰는 중…"}
            </span>
            {elapsed >= 2 ? <small>{elapsed}초 · 처음 여는 페이지는 20초 정도 걸려요</small> : null}
          </div>
          <div aria-hidden="true" className="study-note-skeleton">
            <i style={{ width: "62%" }} />
            <i className="study-note-skeleton-block" />
            <i style={{ width: "38%" }} />
            <i style={{ width: "92%" }} />
            <i style={{ width: "84%" }} />
            <i style={{ width: "44%" }} />
            <i style={{ width: "96%" }} />
            <i style={{ width: "70%" }} />
          </div>
        </div>
      ) : null}
      {state.status === "error" ? (
        <div className="study-note-error">
          <p className="admin-alert" role="alert">{state.message}</p>
          <button className="voice-secondary" onClick={() => setAttempt((n) => n + 1)} type="button">
            다시 시도
          </button>
        </div>
      ) : null}
      {state.status === "ready" ? (
        <article>
          <h2>{state.note.title || `p.${page} 해설`}</h2>
          {state.note.summary ? (
            <div className="study-note-summary">
              <b>핵심</b>
              <MathText className="study-note-text" text={state.note.summary} />
            </div>
          ) : null}
          {state.note.points.length ? (
            <ul className="study-note-points">
              {state.note.points.map((point, index) => (
                <li key={index}>
                  {point.label ? (
                    <strong>
                      <MathText className="study-note-label" text={point.label} />
                    </strong>
                  ) : null}
                  <MathText className="study-note-text" text={point.text} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="study-note-empty">이 페이지에서 정리할 글자 내용을 찾지 못했어요.</p>
          )}
          {state.note.pitfalls ? (
            <div className="study-note-pitfall">
              <b>헷갈리기 쉬운 점</b>
              <MathText className="study-note-text" text={state.note.pitfalls} />
            </div>
          ) : null}
          {onAsk ? (
            <button className="study-note-ask" onClick={onAsk} type="button">
              이 페이지에 대해 COURSE AGENT에게 질문하기
            </button>
          ) : null}
        </article>
      ) : null}
    </aside>
  );
}
