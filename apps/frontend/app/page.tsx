import type { ChatLog, Course, CourseMaterial } from "@skku-course-agent/shared";

const now = new Date("2026-07-09T00:00:00.000Z").toISOString();

const courses: Course[] = [
  {
    id: "course-ai-101",
    code: "AIX101",
    title: "AI 기초와 응용",
    term: "2026-2",
    instructorId: "user-prof-kim",
    agentStatus: "active",
    createdAt: now,
    updatedAt: now
  },
  {
    id: "course-ml-201",
    code: "ML201",
    title: "머신러닝",
    term: "2026-2",
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
      "RAG는 질문과 관련된 강의자료 조각을 먼저 검색한 뒤, 그 근거를 함께 사용해 답변을 생성합니다.",
    citations: [
      {
        materialId: "material-week-02",
        chunkId: "chunk-week-02-03",
        title: "2주차 RAG 개요",
        page: 7,
        score: 0.82,
        snippet: "검색된 문서 조각을 생성 모델의 컨텍스트로 사용한다."
      }
    ],
    latencyMs: 840,
    createdAt: now
  }
];

export default function Home() {
  const activeCourse = courses[0];
  const readyMaterials = materials.filter((material) => material.status === "ready");

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">성균관대학교 AI중심대학사업</p>
          <h1>코스 에이전트 MVP</h1>
        </div>
        <div className="status-pill" data-status={activeCourse.agentStatus}>
          {activeCourse.agentStatus === "active" ? "에이전트 활성" : "준비 중"}
        </div>
      </header>

      <section className="workspace-grid" aria-label="코스 에이전트 작업 영역">
        <aside className="panel course-panel">
          <div className="panel-heading">
            <h2>과목</h2>
            <span>{courses.length}</span>
          </div>
          <div className="course-list">
            {courses.map((course) => (
              <button
                className="course-button"
                data-selected={course.id === activeCourse.id}
                key={course.id}
                type="button"
              >
                <span>{course.code}</span>
                <strong>{course.title}</strong>
                <small>{course.term}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="panel chat-panel">
          <div className="panel-heading">
            <div>
              <h2>{activeCourse.title}</h2>
              <p>{activeCourse.code} · {activeCourse.term}</p>
            </div>
            <span>{readyMaterials.length}개 자료 준비</span>
          </div>

          <div className="message-list" aria-label="질의응답 내역">
            {chatLogs.map((log) => (
              <article className="message" data-role={log.role} key={log.id}>
                <p>{log.message}</p>
                {log.citations.length > 0 ? (
                  <div className="citations">
                    {log.citations.map((citation) => (
                      <span key={citation.chunkId}>
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
            />
            <button type="submit">질문 보내기</button>
          </form>
        </section>

        <aside className="side-stack">
          <section className="panel">
            <div className="panel-heading">
              <h2>강의자료</h2>
              <button type="button">업로드</button>
            </div>
            <div className="material-list">
              {materials.map((material) => (
                <div className="material-row" key={material.id}>
                  <div>
                    <strong>{material.title}</strong>
                    <small>{material.fileName}</small>
                  </div>
                  <span data-status={material.status}>{material.status}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <h2>관리</h2>
              <span>오늘</span>
            </div>
            <dl className="stats">
              <div>
                <dt>질문</dt>
                <dd>128</dd>
              </div>
              <div>
                <dt>평균 응답</dt>
                <dd>0.9s</dd>
              </div>
              <div>
                <dt>활성 과목</dt>
                <dd>1</dd>
              </div>
            </dl>
          </section>
        </aside>
      </section>
    </main>
  );
}
