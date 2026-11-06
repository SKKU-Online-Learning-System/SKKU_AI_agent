"use client";

import { useEffect, useState } from "react";
import { ApiError, listChatSessions } from "../../lib/api";
import type { ChatSessionSummary } from "../../lib/api";
import { UiIcon } from "../ui/ui-icon";

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "-"
    : parsed.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

/** This course's past conversations; picking one reopens it in the agent drawer. */
export function HistoryPanel({
  activeSessionId,
  courseId,
  onClose,
  onSelect
}: {
  activeSessionId: string | null;
  courseId: string;
  onClose: () => void;
  onSelect: (sessionId: string) => void;
}) {
  const [sessions, setSessions] = useState<ChatSessionSummary[] | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    listChatSessions().then(
      (list) => {
        if (!isCancelled) setSessions(list.filter((session) => session.courseId === courseId));
      },
      (error) => {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "대화 이력을 불러오지 못했습니다."
          );
        }
      }
    );
    return () => {
      isCancelled = true;
    };
  }, [courseId]);

  return (
    <section aria-label="대화 이력" className="study-panel">
      <header className="study-panel-head">
        <h2>대화 이력</h2>
        <button aria-label="패널 닫기" onClick={onClose} type="button">
          <UiIcon name="close" />
        </button>
      </header>
      <div className="study-panel-scroll study-history">
        {errorMessage ? <p className="admin-alert" role="alert">{errorMessage}</p> : null}
        {!errorMessage && sessions === null ? (
          <p className="study-panel-empty">대화 이력을 불러오는 중…</p>
        ) : null}
        {sessions && sessions.length === 0 ? (
          <p className="study-panel-empty">이 과목에서 나눈 대화가 아직 없어요.</p>
        ) : null}
        {sessions && sessions.length > 0 ? (
          <ul>
            {sessions.map((session) => (
              <li key={session.id}>
                <button
                  aria-current={session.id === activeSessionId ? "true" : undefined}
                  className="study-history-item"
                  onClick={() => onSelect(session.id)}
                  type="button"
                >
                  <strong>{session.title ?? "제목 없는 대화"}</strong>
                  <small>
                    {formatDateTime(session.lastMessageAt)} · 질문 {session.messageCount}개
                  </small>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
