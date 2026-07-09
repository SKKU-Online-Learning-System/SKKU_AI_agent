import Image from "next/image";
import type { ChatLog, Course, CourseMaterial } from "@skku-course-agent/shared";

const now = new Date("2026-07-09T00:00:00.000Z").toISOString();

type IconName =
  | "account"
  | "dashboard"
  | "course"
  | "group"
  | "calendar"
  | "message"
  | "posts"
  | "mypage"
  | "info"
  | "timetable"
  | "school"
  | "content"
  | "material"
  | "upload"
  | "source"
  | "shield"
  | "send"
  | "question"
  | "bolt"
  | "chart";

const courses: Course[] = [
  {
    id: "course-ai-101",
    code: "SWE2026_41",
    title: "문제해결 SWE2026_41(조재민)",
    term: "2026-1",
    instructorId: "user-prof-kim",
    agentStatus: "active",
    createdAt: now,
    updatedAt: now
  },
  {
    id: "course-ml-201",
    code: "ICE3045_42",
    title: "기계학습개론 ICE3045_42(권근)",
    term: "2026-1",
    instructorId: "user-prof-lee",
    agentStatus: "draft",
    createdAt: now,
    updatedAt: now
  }
];

const materials: CourseMaterial[] = [
  {
    id: "material-week-01",
    courseId: "course-ai-101",
    uploadedBy: "user-prof-kim",
    title: "1주차 강의자료",
    fileName: "week01-introduction.pdf",
    fileType: "application/pdf",
    storageUri: "local://uploads/course-ai-101/week01-introduction.pdf",
    status: "ready",
    checksum: null,
    createdAt: now,
    updatedAt: now
  },
  {
    id: "material-week-02",
    courseId: "course-ai-101",
    uploadedBy: "user-prof-kim",
    title: "2주차 RAG 개요",
    fileName: "week02-rag.pdf",
    fileType: "application/pdf",
    storageUri: "local://uploads/course-ai-101/week02-rag.pdf",
    status: "processing",
    checksum: null,
    createdAt: now,
    updatedAt: now
  }
];

const chatLogs: ChatLog[] = [
  {
    id: "log-001",
    sessionId: "session-demo",
    courseId: "course-ai-101",
    userId: "student-demo",
    role: "user",
    message: "RAG가 일반 LLM 질의응답과 다른 점은 무엇인가요?",
    citations: [],
    latencyMs: null,
    createdAt: now
  },
  {
    id: "log-002",
    sessionId: "session-demo",
    courseId: "course-ai-101",
    userId: "student-demo",
    role: "assistant",
    message:
      "RAG는 질문과 관련된 강의자료 조각을 먼저 검색한 뒤, 그 근거를 함께 사용해 답변을 생성합니다. 그래서 업로드된 수업 자료를 우선 반영하고, 답변 하단에서 참고한 자료를 확인할 수 있습니다.",
    citations: [
      {
        materialId: "material-week-02",
        chunkId: "chunk-week-02-03",
        title: "2주차 RAG 개요",
        page: 7,
        score: 0.82,
        snippet: "검색된 문서 조각은 생성 모델의 컨텍스트로 사용된다."
      }
    ],
    latencyMs: 840,
    createdAt: now
  }
];

const railItems: Array<{ label: string; icon: IconName; active?: boolean }> = [
  { label: "계정", icon: "account" },
  { label: "대시보드", icon: "dashboard" },
  { label: "과목", icon: "course", active: true },
  { label: "그룹", icon: "group" },
  { label: "캘린더", icon: "calendar" },
  { label: "메시지함", icon: "message" },
  { label: "전체게시물", icon: "posts" },
  { label: "마이페이지", icon: "mypage" },
  { label: "이용안내", icon: "info" },
  { label: "시간표", icon: "timetable" }
];

const weekProgress = [
  { week: "01", state: "done" },
  { week: "02", state: "current" },
  { week: "03", state: "open" },
  { week: "04", state: "open" },
  { week: "05", state: "done" },
  { week: "06", state: "open" },
  { week: "07", state: "open" },
  { week: "08", state: "locked" }
];

const materialStatusText: Record<CourseMaterial["status"], string> = {
  uploaded: "업로드됨",
  processing: "처리 중",
  ready: "준비 완료",
  failed: "실패"
};

function UiIcon({ name, className = "" }: { name: IconName; className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={`ui-icon ${className}`.trim()}
      fill="none"
      viewBox="0 0 24 24"
    >
      {name === "account" ? (
        <>
          <circle cx="12" cy="8.1" r="3.1" />
          <path d="M5.8 19.2c.9-3.7 3.1-5.6 6.2-5.6s5.3 1.9 6.2 5.6" />
          <circle cx="12" cy="12" r="10" />
        </>
      ) : null}
      {name === "dashboard" ? (
        <>
          <path d="M4.2 14.2a7.8 7.8 0 0 1 15.6 0" />
          <path d="M12 14.2l3.1-4.2" />
          <path d="M5.4 18.6h13.2" />
          <path d="M7 12.4h1.5M15.5 12.4H17" />
        </>
      ) : null}
      {name === "course" ? (
        <>
          <path d="M6 4.8h10.8c.7 0 1.2.5 1.2 1.2v13.2H7.2A2.2 2.2 0 0 1 5 17V5.8c0-.6.4-1 1-1Z" />
          <path d="M7.2 19.2A2.2 2.2 0 0 1 5 17c0-1.2 1-2.2 2.2-2.2H18" />
          <path d="M8.3 8h6.4M8.3 10.8h6.4" />
        </>
      ) : null}
      {name === "group" ? (
        <>
          <circle cx="12" cy="8" r="2.6" />
          <path d="M7.5 18c.7-3 2.2-4.5 4.5-4.5s3.8 1.5 4.5 4.5" />
          <circle cx="6.5" cy="10" r="2" />
          <path d="M3.4 18c.4-2 1.4-3.2 3.1-3.5" />
          <circle cx="17.5" cy="10" r="2" />
          <path d="M20.6 18c-.4-2-1.4-3.2-3.1-3.5" />
        </>
      ) : null}
      {name === "calendar" ? (
        <>
          <rect x="4.5" y="5.7" width="15" height="14" rx="1.6" />
          <path d="M8 3.8v4M16 3.8v4M4.5 10h15" />
          <path d="M8 13h2M12 13h2M16 13h1M8 16h2M12 16h2M16 16h1" />
        </>
      ) : null}
      {name === "message" ? (
        <>
          <rect x="4.8" y="4.2" width="13.2" height="15.6" rx="1.3" />
          <path d="M8.2 8h6.4M8.2 11.2h7.9M8.2 14.4h5.1" />
          <path d="M18 7.1h1.4v15.6H7.6v-1.3" />
        </>
      ) : null}
      {name === "posts" ? (
        <>
          <rect x="6.3" y="4.4" width="11.4" height="16" rx="1.4" />
          <path d="M9.1 4.4c.2-1 1-1.6 2.9-1.6s2.7.6 2.9 1.6" />
          <path d="M9.2 8.4h5.6M9.2 11.6h5.6M9.2 14.8h4.2" />
        </>
      ) : null}
      {name === "mypage" ? (
        <>
          <rect x="4.4" y="4.2" width="15.2" height="15.2" rx="1.4" />
          <path d="M8 5.8v5h4.1v-5M15.2 6.2v4.4M13.2 8.4h4" />
          <path d="M7.3 14.1h4.4M7.3 16.9h9.3" />
        </>
      ) : null}
      {name === "info" ? (
        <>
          <circle cx="12" cy="12" r="9.2" />
          <path d="M9.3 9.1A2.8 2.8 0 0 1 12 7.5c1.8 0 3 1.1 3 2.7 0 1.3-.7 2-1.8 2.7-.9.6-1.2 1-1.2 2" />
          <path d="M12 18h.1" />
        </>
      ) : null}
      {name === "timetable" ? (
        <>
          <rect x="4.4" y="5.2" width="15.2" height="14.4" rx="1.4" />
          <path d="M8 3.6v3.8M16 3.6v3.8M4.4 9.3h15.2" />
          <path d="M7.6 12.4h2.2M12.4 12.4h2.2M7.6 15.6h2.2" />
          <circle cx="16.4" cy="16.1" r="2.8" />
          <path d="M16.4 14.6v1.7l1.2.8" />
        </>
      ) : null}
      {name === "school" ? (
        <>
          <path d="M3.8 10.5 12 5l8.2 5.5" />
          <path d="M6 10.5v8h12v-8" />
          <path d="M9 18.5v-4h6v4M8.5 12.2h1.8M13.7 12.2h1.8" />
        </>
      ) : null}
      {name === "content" ? (
        <>
          <rect x="4" y="5" width="6.5" height="6.5" rx="1.1" />
          <rect x="13.5" y="4.5" width="6.5" height="6.5" rx="1.1" />
          <rect x="8.8" y="14" width="6.5" height="6.5" rx="1.1" />
          <path d="M10.5 8.2h3M12 11.5v2.5" />
        </>
      ) : null}
      {name === "material" ? (
        <>
          <path d="M7 3.8h7.2L18 7.6v12.6H7z" />
          <path d="M14.2 3.8v3.8H18M9.3 11.3h5.4M9.3 14h5.4M9.3 16.7h3.5" />
        </>
      ) : null}
      {name === "upload" ? (
        <>
          <path d="M12 15.5V5.2M8.4 8.8 12 5.2l3.6 3.6" />
          <path d="M5.5 14.5v4.2h13v-4.2" />
        </>
      ) : null}
      {name === "source" ? (
        <>
          <circle cx="10.5" cy="10.5" r="5.6" />
          <path d="m15 15 4.6 4.6" />
          <path d="M8.2 10.5h4.6M10.5 8.2v4.6" />
        </>
      ) : null}
      {name === "shield" ? (
        <>
          <path d="M12 3.8 18.2 6v5.1c0 4.1-2.5 7-6.2 9.1-3.7-2.1-6.2-5-6.2-9.1V6z" />
          <path d="M12 8.2v5.1M12 16.5v.1" />
        </>
      ) : null}
      {name === "send" ? (
        <>
          <path d="M4 11.7 20 4.8l-6.8 15.7-2.3-6.5z" />
          <path d="m10.9 14 4.1-4.3" />
        </>
      ) : null}
      {name === "question" ? (
        <>
          <path d="M9.2 9.2A3.1 3.1 0 0 1 12 7.5c1.8 0 3.1 1.1 3.1 2.8 0 1.4-.8 2.1-1.9 2.8-.9.6-1.2 1.1-1.2 2.1" />
          <path d="M12 18h.1" />
        </>
      ) : null}
      {name === "bolt" ? <path d="M13 3.8 6.4 13h5.1L11 20.2l6.6-9.5h-5z" /> : null}
      {name === "chart" ? (
        <>
          <path d="M4.8 18.8h14.4M6.5 16l3.8-4.1 3.1 2.4 4.1-6" />
          <path d="M17.5 8.3v4h-4" />
        </>
      ) : null}
    </svg>
  );
}

export default function Home() {
  const activeCourse = courses[0];
  const readyMaterials = materials.filter((material) => material.status === "ready");

  return (
    <main className="campus-shell">
      <aside className="global-rail" aria-label="성균관대학교 학습 메뉴">
        <div className="school-seal" aria-label="Sungkyunkwan University">
          <Image alt="성균관대학교" height={1920} priority src="/skku-logo-white.PNG" width={1920} />
        </div>
        <nav className="rail-nav">
          {railItems.map((item) => (
            <button
              aria-current={item.active ? "page" : undefined}
              className="rail-button"
              data-icon={item.icon}
              key={item.label}
              type="button"
            >
              <UiIcon name={item.icon} />
              {item.label}
            </button>
          ))}
        </nav>
      </aside>

      <div className="learning-frame">
        <header className="course-topbar">
          <button className="menu-button" type="button" aria-label="메뉴 열기">
            <span />
            <span />
            <span />
          </button>
          <div className="breadcrumb">
            <strong>{activeCourse.title}</strong>
            <span aria-hidden="true">›</span>
            <span>AI 학습 AGENT</span>
          </div>
          <div className="learner-chip">학습자 화면</div>
        </header>

        <section className="course-strip" aria-label="주차별 학습 현황">
          <div>
            <p>
              <UiIcon name="school" />
              2026년 1학기
            </p>
            <h1>{activeCourse.title}</h1>
          </div>
          <div className="week-pager">
            {weekProgress.map((week) => (
              <span className="week-dot" data-state={week.state} key={week.week}>
                {week.week}
              </span>
            ))}
          </div>
        </section>

        <section className="content-grid" aria-label="수업 AI 학습 공간">
          <aside className="course-list-panel">
            <div className="panel-title">
              <span>
                <UiIcon name="course" />
                내 과목
              </span>
              <strong>{courses.length}</strong>
            </div>
            <div className="course-list">
              {courses.map((course) => (
                <button
                  className="course-card"
                  data-selected={course.id === activeCourse.id}
                  key={course.id}
                  type="button"
                >
                  <UiIcon className="course-icon" name="course" />
                  <span className="course-code">{course.code}</span>
                  <strong>{course.title}</strong>
                  <small>{course.term}</small>
                </button>
              ))}
            </div>
          </aside>

          <section className="agent-panel">
            <div className="agent-header">
              <div>
                <p>
                  <UiIcon name="content" />
                  강의자료 기반 질의응답
                </p>
                <h2>{activeCourse.code} 학습 AGENT</h2>
              </div>
              <span className="status-pill" data-status={activeCourse.agentStatus}>
                {activeCourse.agentStatus === "active" ? "활성" : "준비 중"}
              </span>
            </div>

            <div className="agent-notice">
              <UiIcon name="shield" />
              답변은 업로드된 강의자료를 우선 사용하며, 자료가 부족하면 부족하다고 알려줍니다.
            </div>

            <div className="message-list" aria-label="질의응답 내역">
              {chatLogs.map((log) => (
                <article className="message" data-role={log.role} key={log.id}>
                  <p>{log.message}</p>
                  {log.citations.length > 0 ? (
                    <div className="citations" aria-label="참고 자료">
                      {log.citations.map((citation) => (
                        <span key={citation.chunkId}>
                          <UiIcon name="source" />
                          {citation.title}
                          {citation.page ? ` p.${citation.page}` : ""}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))}
            </div>

            <form className="composer">
              <input
                aria-label="질문"
                defaultValue="강의자료 기준으로 핵심 개념을 정리해줘"
                name="question"
                suppressHydrationWarning
              />
              <button type="submit">
                <UiIcon name="send" />
                질문 보내기
              </button>
            </form>
          </section>

          <aside className="learning-side">
            <section className="side-panel">
              <div className="panel-title">
                <span>
                  <UiIcon name="material" />
                  강의자료
                </span>
                <button type="button">
                  <UiIcon name="upload" />
                  업로드
                </button>
              </div>
              <div className="material-list">
                {materials.map((material) => (
                  <div className="material-row" key={material.id}>
                    <UiIcon className="material-icon" name="material" />
                    <div>
                      <strong>{material.title}</strong>
                      <small>{material.fileName}</small>
                    </div>
                    <span className="material-status" data-status={material.status}>
                      {materialStatusText[material.status]}
                    </span>
                  </div>
                ))}
              </div>
            </section>

            <section className="side-panel">
              <div className="panel-title">
                <span>
                  <UiIcon name="chart" />
                  오늘의 현황
                </span>
                <strong>LIVE</strong>
              </div>
              <dl className="stats">
                <div>
                  <dt>
                    <UiIcon name="question" />
                    질문
                  </dt>
                  <dd>128</dd>
                </div>
                <div>
                  <dt>
                    <UiIcon name="bolt" />
                    평균 응답
                  </dt>
                  <dd>0.9s</dd>
                </div>
                <div>
                  <dt>
                    <UiIcon name="material" />
                    준비된 자료
                  </dt>
                  <dd>{readyMaterials.length}</dd>
                </div>
              </dl>
            </section>
          </aside>
        </section>
      </div>
    </main>
  );
}
