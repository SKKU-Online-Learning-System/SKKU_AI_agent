import { UiIcon } from "../ui/ui-icon";

export function CourseChatPanel() {
  return (
    <section className="canvas-course-chat">
      <header>
        <h1>AI 질문</h1>
        <p>선택한 과목의 업로드 자료를 우선 사용하는 코스 에이전트입니다.</p>
      </header>
      <p className="safe-notice">
        <UiIcon name="shield" /> SAFE: 강의자료를 우선하고 근거가 부족하면 명시합니다.
      </p>
      <div className="canvas-chat-empty">
        <UiIcon name="agent" />
        <strong>과목별 AI 질문 공간</strong>
        <p>질문·출처·대화 기록 API가 연결되는 단계에서 이 과목의 대화가 표시됩니다.</p>
      </div>
    </section>
  );
}
