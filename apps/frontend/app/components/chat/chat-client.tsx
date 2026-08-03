"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  ApiError,
  askCourseAgent,
  getChatSession,
  getCourseRagStatus,
  listCourses
} from "../../lib/api";
import type {
  AnswerSource,
  AnswerSourceType,
  ChatAnswer,
  CourseRagStatus,
  CourseSummary
} from "../../lib/api";

const maxQuestionLength = 2000;

const answerBadgeLabels: Record<AnswerSourceType, string> = {
  rag: "강의자료 기반 답변",
  general_llm: "일반 개념 설명",
  no_material: "자료 부족",
  safety_response: "안전 안내"
};

type ChatMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      text: string;
      sources: AnswerSource[];
      answerSourceType: AnswerSourceType;
    };

type ChatClientProps = {
  courseId: string;
  initialSessionId?: string | null;
};

function apiErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function ragStatusMessage(status: CourseRagStatus | null): string {
  if (!status) return "검색 준비 상태를 확인하고 있습니다.";
  if (status.isSearchReady) return "이 과목은 검색 준비가 완료되었습니다.";
  if (status.pendingMaterialCount > 0) {
    return "업로드된 자료가 아직 처리되지 않았습니다. 교수자에게 자료 처리를 요청해 주세요.";
  }

  return "처리된 강의자료가 없어 일반 개념 설명만 제공될 수 있습니다.";
}

function sourceLabel(source: AnswerSource): string {
  const page =
    source.pageNumber === null || source.pageNumber === undefined
      ? "페이지 정보 없음"
      : `p.${source.pageNumber}`;
  return `${source.documentName} (${page})`;
}

export function ChatClient({ courseId, initialSessionId = null }: ChatClientProps) {
  const [course, setCourse] = useState<CourseSummary | null>(null);
  const [ragStatus, setRagStatus] = useState<CourseRagStatus | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId);
  const [isLoading, setIsLoading] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const messageCounter = useRef(0);

  const nextMessageId = (prefix: string) => {
    messageCounter.current += 1;
    return `${prefix}-${messageCounter.current}`;
  };

  useEffect(() => {
    let isCancelled = false;

    async function loadCourseContext() {
      setIsLoading(true);
      try {
        const [courseList, status] = await Promise.all([
          listCourses(),
          getCourseRagStatus(courseId)
        ]);
        if (isCancelled) return;
        setCourse(courseList.find((item) => item.id === courseId) ?? null);
        setRagStatus(status);

        if (initialSessionId) {
          const detail = await getChatSession(initialSessionId);
          if (isCancelled) return;
          setMessages(
            detail.logs.flatMap((log) => [
              { id: `${log.id}-q`, role: "user" as const, text: log.question },
              {
                id: `${log.id}-a`,
                role: "assistant" as const,
                text: log.answer,
                sources: log.sources,
                answerSourceType: log.answerSourceType
              }
            ])
          );
        }
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(apiErrorMessage(error, "챗봇 화면을 불러오지 못했습니다."));
        }
      } finally {
        if (!isCancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadCourseContext();

    return () => {
      isCancelled = true;
    };
  }, [courseId, initialSessionId]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || isSending) return;

    setErrorMessage(null);
    setIsSending(true);
    setMessages((current) => [
      ...current,
      { id: nextMessageId("user"), role: "user", text: trimmed }
    ]);
    setQuestion("");

    try {
      const answer: ChatAnswer = await askCourseAgent({
        courseId,
        question: trimmed,
        chatSessionId: sessionId
      });
      setSessionId(answer.sessionId);
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId("assistant"),
          role: "assistant",
          text: answer.answer,
          sources: answer.sources,
          answerSourceType: answer.answerSourceType
        }
      ]);
    } catch (error) {
      setErrorMessage(apiErrorMessage(error, "답변을 받지 못했습니다."));
    } finally {
      setIsSending(false);
    }
  };

  return (
    <section className="chat-page">
      <header className="chat-header">
        <h1>{course ? course.title : "과목 챗봇"}</h1>
        <p>{course ? `담당 교수 ${course.instructorName}` : "과목 정보를 불러오는 중입니다."}</p>
        <p className="chat-rag-status" data-ready={ragStatus?.isSearchReady ? "true" : "false"}>
          {ragStatusMessage(ragStatus)}
        </p>
      </header>

      {errorMessage ? (
        <p className="admin-alert" role="alert">
          {errorMessage}
        </p>
      ) : null}

      <div className="chat-messages">
        {isLoading ? (
          <p className="empty-state">대화 내용을 불러오고 있습니다.</p>
        ) : messages.length === 0 ? (
          <p className="empty-state">
            강의자료에 대해 궁금한 점을 질문해 보세요. 답변에는 사용된 자료가 함께 표시됩니다.
          </p>
        ) : (
          messages.map((message) =>
            message.role === "user" ? (
              <article className="chat-bubble" data-role="user" key={message.id}>
                <p>{message.text}</p>
              </article>
            ) : (
              <article className="chat-bubble" data-role="assistant" key={message.id}>
                <span className="chat-badge" data-source={message.answerSourceType}>
                  {answerBadgeLabels[message.answerSourceType]}
                </span>
                <p>{message.text}</p>
                {message.sources.length > 0 ? (
                  <div className="chat-sources">
                    <strong>출처</strong>
                    <ul>
                      {message.sources.map((source) => (
                        <li key={`${source.materialId}-${source.chunkIndex}`}>
                          {sourceLabel(source)}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </article>
            )
          )
        )}
        {isSending ? <p className="empty-state">답변을 생성하고 있습니다.</p> : null}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <label htmlFor="chat-question">질문</label>
        <textarea
          disabled={isSending}
          id="chat-question"
          maxLength={maxQuestionLength}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="예: 경사하강법이 뭐야?"
          rows={3}
          value={question}
        />
        <button disabled={isSending || question.trim().length === 0} type="submit">
          {isSending ? "전송 중..." : "질문 보내기"}
        </button>
      </form>

      <p className="chat-disclaimer">
        AI 답변은 학습 보조용이며, 최종 판단은 강의자료와 교수자 안내를 따르세요.
      </p>
    </section>
  );
}
