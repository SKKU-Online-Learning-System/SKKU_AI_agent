"use client";

import { demoConversations, demoCourses, studentInitialMessages } from "./demo-data";
import Image from "next/image";
import { EmptyState, StatusBadge } from "./screen-primitives";
import type { ScreenId } from "./state";
import { UiIcon } from "./ui-icon";

export function StudentScreen({ screen }: { screen: ScreenId }) {
  if (screen === "student-login") {
    return <section className="content-page"><h1>로그인</h1><p className="page-lead">성균관대학교 계정으로 코스 에이전트를 이용하세요.</p><div className="login-panel"><Image src="/skku-logo.svg" alt="성균관대학교" width={78} height={78} /><button type="button" className="primary-button">학교 계정으로 로그인</button><button type="button">서비스 계정으로 로그인</button></div></section>;
  }
  if (screen === "student-courses") {
    return <section className="content-page"><h1>내 과목</h1><p className="page-lead">접근 가능한 2026년 1학기 과목입니다.</p><div className="course-card-grid">{demoCourses.map((course) => <article className="course-card" key={course.id}><span className="course-code">{course.code}</span><h2>{course.title}</h2><p>2026년 1학기</p><StatusBadge tone={course.agentStatus}>{course.agentStatus === "active" ? "에이전트 활성" : "에이전트 비활성"}</StatusBadge><button type="button" disabled={course.agentStatus !== "active"}>과목 열기</button></article>)}</div></section>;
  }
  if (screen === "student-history") {
    return <section className="content-page"><h1>최근 대화</h1><div className="list-panel">{demoConversations.map((conversation) => <button type="button" className="conversation-row" key={conversation.id}><strong>{conversation.question}</strong><span>{conversation.answer}</span><time>{conversation.createdAt}</time></button>)}</div></section>;
  }
  if (screen !== "student-chat") return <EmptyState title="화면을 찾을 수 없습니다" detail="학생 메뉴에서 다시 선택해 주세요." />;
  return <section className="content-page chat-preview"><h1>AI 코스 에이전트</h1><p className="safe-notice"><UiIcon name="shield" /> SAFE: 강의자료를 우선하고 근거가 부족하면 명시합니다.</p><div className="message-list">{studentInitialMessages.map((message) => <article className="message" data-role={message.role} key={message.id}><p>{message.message}</p>{message.citations.map((citation) => <span className="source-chip" key={citation.title}><UiIcon name="source" /> {citation.title} p.{citation.page}</span>)}</article>)}</div><div className="composer-preview"><textarea aria-label="질문 미리보기" placeholder="강의자료에 대해 질문하세요" /><button type="button" className="primary-button"><UiIcon name="send" /> 질문 보내기</button></div><p className="learning-notice">AI 답변은 학습 보조용이며, 최종 판단은 강의자료와 교수자 안내를 따르세요.</p></section>;
}
