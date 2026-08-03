"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, listChatSessions } from "../../lib/api";
import type { ChatSessionSummary } from "../../lib/api";

function formatDateTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "-" : parsed.toLocaleString("ko-KR");
}

export function ChatHistoryClient() {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    async function loadSessions() {
      try {
        const sessionList = await listChatSessions();
        if (!isCancelled) setSessions(sessionList);
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "대화 이력을 불러오지 못했습니다."
          );
        }
      } finally {
        if (!isCancelled) setIsLoading(false);
      }
    }

    void loadSessions();

    return () => {
      isCancelled = true;
    };
  }, []);

  return (
    <section className="course-list-page">
      <header>
        <h1>대화 이력</h1>
        <p>이전에 나눈 과목별 대화를 다시 열어 이어서 질문할 수 있습니다.</p>
      </header>

      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}

      <div className="course-table-wrap">
        <table className="course-table">
          <thead>
            <tr>
              <th scope="col">대화</th>
              <th scope="col">과목</th>
              <th scope="col">질문 수</th>
              <th scope="col">마지막 대화</th>
              <th scope="col">작업</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5}>대화 이력을 불러오고 있습니다.</td>
              </tr>
            ) : sessions.length === 0 ? (
              <tr>
                <td className="empty-state" colSpan={5}>
                  저장된 대화가 없습니다.
                </td>
              </tr>
            ) : (
              sessions.map((session) => (
                <tr key={session.id}>
                  <td>
                    <strong>{session.title ?? "제목 없는 대화"}</strong>
                  </td>
                  <td>{session.courseName}</td>
                  <td>{session.messageCount}</td>
                  <td>{formatDateTime(session.lastMessageAt)}</td>
                  <td>
                    <Link href={`/student/chat-history/${session.id}`}>이어서 보기</Link>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
