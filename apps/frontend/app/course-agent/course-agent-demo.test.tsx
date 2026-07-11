import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import CourseAgentDemo from "./course-agent-demo";

describe("CourseAgentDemo", () => {
  it("renders the initial student iCampus course agent shell", () => {
    const html = renderToStaticMarkup(<CourseAgentDemo />);

    expect(html).toContain('class="icampus-shell"');
    expect(html).toContain('aria-label="글로벌 내비게이션"');
    expect(html).toContain('class="course-workspace"');
    expect(html).toContain('class="course-header"');
    expect(html).toContain('aria-label="과목 탐색 메뉴"');
    expect(html).toContain('aria-labelledby="agent-title"');
    expect(html).toContain("문제해결_SWE2026_41(조재민)");
    expect(html).toContain('class="role-switch"');
    expect(html).toContain('<button type="button" aria-pressed="true">학생</button>');
    expect(html).toContain('<button type="button" aria-pressed="false">교수</button>');
    expect(html).toContain("AI 코스 에이전트");
    expect(html).toContain("SAFE");
    expect(html).toContain("RAG가 일반 LLM 질의응답과 다른 점은 무엇인가요?");
    expect(html).toContain("2주차 RAG 개요 p.7");
    expect(html).toContain("답변 성격");
  });
});
