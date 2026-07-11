import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { materials, personalityOptions } from "./demo-data";
import { ProfessorControls, StudentControls } from "./role-controls";
import { createInitialState } from "./state";

describe("StudentControls", () => {
  it("renders every personality and the student attachment types", () => {
    const markup = renderToStaticMarkup(
      <StudentControls state={createInitialState()} dispatch={vi.fn()} />
    );

    for (const option of personalityOptions) {
      expect(markup).toContain(option.label);
    }
    expect(markup).toContain(
      'accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,image/png,image/jpeg"'
    );
  });
});

describe("ProfessorControls", () => {
  it("enables ready materials and disables processing or failed materials", () => {
    const markup = renderToStaticMarkup(
      <ProfessorControls
        materials={materials}
        state={createInitialState()}
        dispatch={vi.fn()}
      />
    );

    expect(markup).toMatch(/material-week-01[^>]*checked/);
    expect(markup).toMatch(/material-week-02[^>]*disabled/);
    expect(markup).toMatch(/material-week-03[^>]*disabled/);
    expect(markup).toContain("processing");
    expect(markup).toContain("failed");
    expect(markup).toContain("전체 선택");
    expect(markup).toContain("전체 해제");
    expect(markup).toContain('accept=".pdf,.pptx,.docx,.txt"');
  });
});
