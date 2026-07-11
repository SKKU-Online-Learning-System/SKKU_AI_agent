"use client";

import { useEffect, useReducer, useState } from "react";
import {
  activeCourse,
  materials,
  personalityOptions,
  professorInitialMessages,
  railItems,
  studentInitialMessages
} from "./demo-data";
import { AdminScreen } from "./admin-screens";
import { roleNavigation } from "./navigation";
import { ProfessorScreen } from "./professor-screens";
import { ProfessorControls, StudentControls } from "./role-controls";
import { StudentScreen } from "./student-screens";
import {
  courseAgentReducer,
  createInitialState,
  type AgentRole,
  type CourseAgentState,
  type DemoMessage
} from "./state";
import { UiIcon } from "./ui-icon";

const SETTINGS_KEY = "skku-course-agent-settings-v1";

function initialState(): CourseAgentState {
  const state = createInitialState();
  return {
    ...state,
    student: { ...state.student, messages: studentInitialMessages },
    professor: { ...state.professor, messages: professorInitialMessages }
  };
}

function isRole(value: unknown): value is AgentRole {
  return value === "student" || value === "professor" || value === "admin";
}

export default function CourseAgentDemo() {
  const [state, dispatch] = useReducer(courseAgentReducer, undefined, initialState);
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(SETTINGS_KEY);
      if (stored) {
        const settings: unknown = JSON.parse(stored);
        if (settings && typeof settings === "object") {
          const candidate = settings as {
            activeRole?: unknown;
            student?: { personality?: unknown };
            professor?: { selectedMaterialIds?: unknown };
          };
          if (isRole(candidate.activeRole)) {
            dispatch({ type: "set-role", role: candidate.activeRole });
          }
          if (
            typeof candidate.student?.personality === "string" &&
            personalityOptions.some((option) => option.id === candidate.student?.personality)
          ) {
            dispatch({
              type: "set-personality",
              personality: candidate.student.personality as CourseAgentState["student"]["personality"]
            });
          }
          if (
            Array.isArray(candidate.professor?.selectedMaterialIds) &&
            candidate.professor.selectedMaterialIds.every((id) => typeof id === "string")
          ) {
            dispatch({
              type: "set-materials",
              materialIds: candidate.professor.selectedMaterialIds as string[]
            });
          }
        }
      }
    } catch {
      // Malformed or unavailable storage must not prevent the demo from loading.
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(
        SETTINGS_KEY,
        JSON.stringify({
          activeRole: state.activeRole,
          student: { personality: state.student.personality },
          professor: { selectedMaterialIds: state.professor.selectedMaterialIds }
        })
      );
    } catch {
      // The UI remains usable when storage is disabled or full.
    }
  }, [hydrated, state.activeRole, state.professor.selectedMaterialIds, state.student.personality]);

  const roleState = state[state.activeRole];
  const canSubmit = question.trim().length > 0 || roleState.attachments.length > 0;
  const navigation = roleNavigation[state.activeRole];
  const activeNavigation = navigation.find((item) => item.id === state.activeScreen);
  const showAgent =
    state.activeScreen === "student-chat" ||
    (state.activeRole === "professor" && state.activeScreen === "professor-dashboard");

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    setSubmitting(true);

    const role = state.activeRole;
    const prompt = question.trim() || "첨부한 자료를 분석해 주세요.";
    dispatch({
      type: "add-message",
      role,
      message: {
        id: `${role}-user-${roleState.messages.length + 1}`,
        role: "user",
        message: prompt,
        citations: []
      }
    });

    let response: DemoMessage;
    if (role === "student") {
      const personality = personalityOptions.find(
        (option) => option.id === state.student.personality
      )?.label;
      const citations = [
        ...(studentInitialMessages.find((message) => message.citations.length)?.citations ?? [])
      ];
      response = {
        id: `student-assistant-${roleState.messages.length + 2}`,
        role: "assistant",
        message: `[${personality}] 강의자료의 근거를 우선해 질문을 정리했습니다: ${prompt}`,
        citations
      };
    } else {
      const selectedCount = state.professor.selectedMaterialIds.length;
      const attachedCount = state.professor.attachments.length;
      const hasContext = selectedCount + attachedCount > 0;
      response = {
        id: `professor-assistant-${roleState.messages.length + 2}`,
        role: "assistant",
        message: hasContext
          ? `선택한 강의자료 ${selectedCount}개와 첨부 자료 ${attachedCount}개를 기준으로 점검했습니다: ${prompt}`
          : "선택하거나 첨부한 강의자료가 없어 근거 기반 답변을 제공할 수 없습니다.",
        citations: [],
        insufficient: !hasContext
      };
    }
    dispatch({ type: "add-message", role, message: response });
    setQuestion("");
    setSubmitting(false);
  };

  return (
    <main className="icampus-shell">
      <aside className="global-navigation" aria-label="글로벌 내비게이션">
        <nav>
          {railItems.map((item) => (
            <button key={item.label} type="button" aria-current={item.active ? "page" : undefined}>
              <UiIcon name={item.icon} />
              {item.label}
            </button>
          ))}
        </nav>
      </aside>
      <div className="course-workspace">
        <header className="course-header">
          <button
            type="button"
            aria-label={menuOpen ? "과목 메뉴 닫기" : "과목 메뉴 열기"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            ☰
          </button>
          <strong>문제해결_SWE2026_41(조재민) 〉 {activeNavigation?.label}</strong>
          <div className="role-switch" role="group" aria-label="사용자 역할">
            <button
              type="button"
              aria-pressed={state.activeRole === "student"}
              onClick={() => dispatch({ type: "set-role", role: "student" })}
            >
              학생
            </button>
            <button
              type="button"
              aria-pressed={state.activeRole === "professor"}
              onClick={() => dispatch({ type: "set-role", role: "professor" })}
            >
              교수
            </button>
            <button
              type="button"
              aria-pressed={state.activeRole === "admin"}
              onClick={() => dispatch({ type: "set-role", role: "admin" })}
            >
              관리자
            </button>
          </div>
        </header>
        <div className="course-layout">
          <aside className="course-navigation" data-open={menuOpen} aria-label="과목 탐색 메뉴">
            <p className="term-label">2026년 1학기</p>
            <nav>
              {navigation.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-current={state.activeScreen === item.id ? "page" : undefined}
                  onClick={() => {
                    dispatch({ type: "set-screen", screen: item.id });
                    setMenuOpen(false);
                  }}
                >
                  <UiIcon name={item.icon} />
                  {item.label}
                </button>
              ))}
            </nav>
          </aside>
          <div className="screen-content">
          {state.activeRole === "student" && state.activeScreen !== "student-chat" ? (
            <StudentScreen screen={state.activeScreen} />
          ) : null}
          {state.activeRole === "professor" ? (
            <ProfessorScreen screen={state.activeScreen} />
          ) : null}
          {state.activeRole === "admin" ? <AdminScreen screen={state.activeScreen} /> : null}
          {showAgent ? <section className="agent-workspace" aria-labelledby="agent-title">
            <h1 id="agent-title">AI 코스 에이전트</h1>
            <p className="safe-notice">
              <UiIcon name="shield" /> SAFE: 강의자료를 우선하고 근거가 부족하면 명시합니다.
            </p>
            <div className="agent-layout">
              <div className="chat-column">
                <div className="message-list" aria-label="질의응답 내역">
                  {roleState.messages.map((message) => (
                    <article
                      className="message"
                      data-role={message.role}
                      data-insufficient={message.insufficient ? "true" : undefined}
                      key={message.id}
                    >
                      <p>{message.message}</p>
                      {message.role === "assistant" && message.citations.length > 0 ? (
                        <div className="citations" aria-label="참고 자료">
                          {message.citations.map((citation) => (
                            <span key={`${citation.title}-${citation.page ?? "none"}`}>
                              <UiIcon name="source" />
                              {citation.title}{citation.page ? ` p.${citation.page}` : ""}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
                <form className="composer" onSubmit={submit}>
                  {roleState.attachments.length > 0 ? (
                    <div className="attachment-context" aria-label="첨부 문맥">
                      {roleState.attachments.map((attachment) => (
                        <span key={attachment.id}>{attachment.name}</span>
                      ))}
                    </div>
                  ) : null}
                  <textarea
                    aria-label="질문"
                    placeholder={`${activeCourse.code} 강의자료에 대해 질문하세요`}
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                  />
                  <button type="submit" disabled={!canSubmit || submitting}>
                    <UiIcon name="send" /> 질문 보내기
                  </button>
                </form>
              </div>
              <aside className="role-controls">
                {state.activeRole === "student" ? (
                  <StudentControls state={state} dispatch={dispatch} />
                ) : state.activeRole === "professor" ? (
                  <ProfessorControls materials={materials} state={state} dispatch={dispatch} />
                ) : null}
              </aside>
            </div>
          </section> : null}
          </div>
        </div>
      </div>
    </main>
  );
}
