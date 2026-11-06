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
  page,
  week
}: {
  courseId: string;
  materialId: string;
  onAsk?: () => void;
  page: number;
  week: number;
}) {
  const cache = useRef(new Map<string, PageNote>());
  const [state, setState] = useState<NoteState>({ status: "loading" });

  useEffect(() => {
    const key = `${materialId}:${page}`;
    const cached = cache.current.get(key);
    if (cached) {
      setState({ status: "ready", note: cached });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    getMaterialPageNote(courseId, materialId, page).then(
      (note) => {
        cache.current.set(key, note);
        if (!cancelled) setState({ status: "ready", note });
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
  }, [courseId, materialId, page]);

  return (
    <aside aria-label="AI 교안 해설" className="study-note">
      <div className="study-note-kicker">
        {week}주차 · p.{page}
      </div>
      {state.status === "loading" ? (
        <div className="study-note-loading" role="status">
          <span className="study-note-shimmer">AI가 이 페이지를 해설하는 중…</span>
          <p>처음 여는 페이지는 몇 초가 걸려요. 한 번 쓴 해설은 바로 열립니다.</p>
        </div>
      ) : null}
      {state.status === "error" ? (
        <p className="admin-alert" role="alert">{state.message}</p>
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
                  {point.label ? <strong>{point.label}</strong> : null}
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
