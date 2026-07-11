import { describe, expect, it } from "vitest";
import {
  courseAgentReducer,
  createInitialState,
  validateAttachment
} from "./state";

describe("courseAgentReducer", () => {
  it("switches roles without mixing role-specific state", () => {
    const studentState = courseAgentReducer(createInitialState(), {
      type: "set-personality",
      personality: "efficient"
    });
    const professorState = courseAgentReducer(studentState, {
      type: "set-role",
      role: "professor"
    });

    expect(professorState.activeRole).toBe("professor");
    expect(professorState.student.personality).toBe("efficient");
    expect(professorState.professor.selectedMaterialIds).toEqual(["material-week-01"]);
  });

  it("only toggles ready professor materials", () => {
    const state = createInitialState();
    const selected = courseAgentReducer(state, {
      type: "toggle-material",
      materialId: "material-week-03",
      selectable: true
    });
    const ignored = courseAgentReducer(selected, {
      type: "toggle-material",
      materialId: "material-week-02",
      selectable: false
    });

    expect(ignored.professor.selectedMaterialIds).toContain("material-week-03");
    expect(ignored.professor.selectedMaterialIds).not.toContain("material-week-02");
  });
});

describe("validateAttachment", () => {
  it("accepts student images and rejects oversized professor files", () => {
    const image = { name: "diagram.png", size: 1024, type: "image/png" } as File;
    const hugePdf = {
      name: "reference.pdf",
      size: 21 * 1024 * 1024,
      type: "application/pdf"
    } as File;

    expect(validateAttachment(image, "student")).toBeNull();
    expect(validateAttachment(hugePdf, "professor")).toBe(
      "교수 참고 문서는 파일당 20MB 이하만 첨부할 수 있습니다."
    );
  });
});
