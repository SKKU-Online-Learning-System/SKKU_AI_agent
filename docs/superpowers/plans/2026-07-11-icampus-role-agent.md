# iCampus Role-Based AI Course Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the frontend as an iCampus-matched course page with a freely switchable student/professor AI course agent, role-specific RAG controls, attachments, personalities, and chat.

**Architecture:** Keep `page.tsx` as a thin route entry and move the interactive demo into focused client components under `apps/frontend/app/course-agent`. Put deterministic role state, attachment validation, and reducer behavior in a pure module covered by Vitest. Preserve shared course/material/chat domain types while keeping demo-only UI types local to the frontend.

**Tech Stack:** Next.js 16 App Router, React 18, TypeScript 5.5, CSS, Vitest, browser `File` API, `localStorage`.

## Global Constraints

- Match the visible structure of `https://canvas.skku.edu/courses/74240`: 84px navy global navigation, about 220px light-gray course navigation, white top bar, flat white content, thin gray rules, restrained rounding and shadows.
- Add `AI 코스 에이전트` to the course navigation and render it selected.
- Default to student mode and allow unrestricted `학생 | 교수` switching without authentication.
- Keep student and professor conversations, selections, and attachment lists independent.
- Professor references accept PDF, PPTX, DOCX, and TXT, maximum 20MB per file.
- Student attachments accept PDF, DOCX, TXT, PNG, JPG, and JPEG, maximum 10MB per file.
- Student personalities are 기본, 전문적, 친근함, 솔직함, 개성 있음, 효율적, 냉소적; personality changes tone only, never citations, SAFE rules, or capabilities.
- This work is frontend-only: do not add authentication, upload APIs, indexing, or live RAG endpoints.
- Preserve course-scoped citations, insufficient-material messaging, and assignment/exam hint behavior.
- Use double quotes and semicolons in TypeScript and keep exported shared-domain types in `packages/shared` unchanged.

---

### Task 1: Add deterministic role-state tests and reducer

**Files:**
- Modify: `apps/frontend/package.json`
- Create: `apps/frontend/app/course-agent/state.ts`
- Create: `apps/frontend/app/course-agent/state.test.ts`

**Interfaces:**
- Produces: `AgentRole`, `PersonalityId`, `AttachmentItem`, `DemoMessage`, `CourseAgentState`, `createInitialState()`, `courseAgentReducer(state, action)`, `validateAttachment(file, role)`.
- Consumes: browser-compatible `File` shape (`name`, `size`, `type`) only; tests may use plain objects cast to `File`.

- [ ] **Step 1: Add Vitest test script and dependency**

Update `apps/frontend/package.json` scripts and dev dependencies:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "vitest": "^3.2.4"
  }
}
```

Run: `npm install`
Expected: workspace lockfile updates and `npm ls vitest` reports `vitest@3.2.4` or a compatible 3.2 patch.

- [ ] **Step 2: Write failing reducer and validation tests**

Create `apps/frontend/app/course-agent/state.test.ts`:

```ts
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
```

- [ ] **Step 3: Run the tests to verify RED**

Run: `npm run test --workspace @skku-course-agent/frontend`
Expected: FAIL because `./state` does not exist.

- [ ] **Step 4: Implement the minimal state module**

Create `apps/frontend/app/course-agent/state.ts` with these exact public types and behavior:

```ts
export type AgentRole = "student" | "professor";
export type PersonalityId =
  | "default"
  | "professional"
  | "friendly"
  | "candid"
  | "quirky"
  | "efficient"
  | "cynical";

export type AttachmentItem = {
  id: string;
  name: string;
  size: number;
  type: string;
  previewUrl?: string;
};

export type DemoMessage = {
  id: string;
  role: "user" | "assistant";
  message: string;
  citations: Array<{ title: string; page?: number }>;
  insufficient?: boolean;
};

export type CourseAgentState = {
  activeRole: AgentRole;
  student: {
    personality: PersonalityId;
    attachments: AttachmentItem[];
    messages: DemoMessage[];
  };
  professor: {
    selectedMaterialIds: string[];
    attachments: AttachmentItem[];
    messages: DemoMessage[];
  };
};

export type CourseAgentAction =
  | { type: "set-role"; role: AgentRole }
  | { type: "set-personality"; personality: PersonalityId }
  | { type: "toggle-material"; materialId: string; selectable: boolean }
  | { type: "set-materials"; materialIds: string[] }
  | { type: "add-attachments"; role: AgentRole; attachments: AttachmentItem[] }
  | { type: "remove-attachment"; role: AgentRole; attachmentId: string }
  | { type: "add-message"; role: AgentRole; message: DemoMessage };

export function createInitialState(): CourseAgentState {
  return {
    activeRole: "student",
    student: { personality: "default", attachments: [], messages: [] },
    professor: {
      selectedMaterialIds: ["material-week-01"],
      attachments: [],
      messages: []
    }
  };
}

export function validateAttachment(file: File, role: AgentRole): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const allowed =
    role === "professor"
      ? ["pdf", "pptx", "docx", "txt"]
      : ["pdf", "docx", "txt", "png", "jpg", "jpeg"];
  const limitMb = role === "professor" ? 20 : 10;
  if (!allowed.includes(extension)) {
    return role === "professor"
      ? "PDF, PPTX, DOCX, TXT 파일만 첨부할 수 있습니다."
      : "PDF, DOCX, TXT, PNG, JPG, JPEG 파일만 첨부할 수 있습니다.";
  }
  if (file.size > limitMb * 1024 * 1024) {
    return `${role === "professor" ? "교수 참고 문서" : "학생 첨부 파일"}는 파일당 ${limitMb}MB 이하만 첨부할 수 있습니다.`;
  }
  return null;
}

export function courseAgentReducer(
  state: CourseAgentState,
  action: CourseAgentAction
): CourseAgentState {
  if (action.type === "set-role") return { ...state, activeRole: action.role };
  if (action.type === "set-personality") {
    return { ...state, student: { ...state.student, personality: action.personality } };
  }
  if (action.type === "toggle-material") {
    if (!action.selectable) return state;
    const selected = state.professor.selectedMaterialIds.includes(action.materialId);
    return {
      ...state,
      professor: {
        ...state.professor,
        selectedMaterialIds: selected
          ? state.professor.selectedMaterialIds.filter((id) => id !== action.materialId)
          : [...state.professor.selectedMaterialIds, action.materialId]
      }
    };
  }
  if (action.type === "set-materials") {
    return { ...state, professor: { ...state.professor, selectedMaterialIds: action.materialIds } };
  }
  if (action.type === "add-attachments") {
    if (action.role === "student") {
      return {
        ...state,
        student: {
          ...state.student,
          attachments: [...state.student.attachments, ...action.attachments]
        }
      };
    }
    return {
      ...state,
      professor: {
        ...state.professor,
        attachments: [...state.professor.attachments, ...action.attachments]
      }
    };
  }
  if (action.type === "remove-attachment") {
    if (action.role === "student") {
      return {
        ...state,
        student: {
          ...state.student,
          attachments: state.student.attachments.filter(
            (attachment) => attachment.id !== action.attachmentId
          )
        }
      };
    }
    return {
      ...state,
      professor: {
        ...state.professor,
        attachments: state.professor.attachments.filter(
          (attachment) => attachment.id !== action.attachmentId
        )
      }
    };
  }
  if (action.role === "student") {
    return {
      ...state,
      student: {
        ...state.student,
        messages: [...state.student.messages, action.message]
      }
    };
  }
  return {
    ...state,
    professor: {
      ...state.professor,
      messages: [...state.professor.messages, action.message]
    }
  };
}
```

- [ ] **Step 5: Run unit tests to verify GREEN**

Run: `npm run test --workspace @skku-course-agent/frontend`
Expected: PASS, 3 tests.

- [ ] **Step 6: Commit the state foundation**

```bash
git add package-lock.json apps/frontend/package.json apps/frontend/app/course-agent/state.ts apps/frontend/app/course-agent/state.test.ts
git commit -m "Add course agent role state"
```

### Task 2: Extract iCampus navigation assets and demo data

**Files:**
- Create: `apps/frontend/app/course-agent/ui-icon.tsx`
- Create: `apps/frontend/app/course-agent/demo-data.ts`

**Interfaces:**
- Produces: `UiIcon`, `IconName`, `activeCourse`, `materials`, `studentInitialMessages`, `professorInitialMessages`, `personalityOptions`, `railItems`, `courseNavItems`.
- Consumes: `Course`, `CourseMaterial` from `@skku-course-agent/shared`; `DemoMessage`, `PersonalityId` from `./state`.

- [ ] **Step 1: Move the existing SVG icon renderer into `ui-icon.tsx`**

Copy the current `UiIcon` paths from `page.tsx`, export `UiIcon` and `IconName`, and add new icon names `home`, `attendance`, `grade`, `agent`, `attachment`, `image`, `close`, `chevron`, and `check`. Each new icon must use the same 24×24, stroke-only visual language.

The public signature must be:

```tsx
export function UiIcon({
  name,
  className = ""
}: {
  name: IconName;
  className?: string;
}) {
  return (
    <svg aria-hidden="true" className={`ui-icon ${className}`.trim()} fill="none" viewBox="0 0 24 24">
      {/* one conditional path group for every IconName */}
    </svg>
  );
}
```

- [ ] **Step 2: Create typed demo data**

Create `demo-data.ts` by moving the active course, three materials (ready, processing, failed), current student messages and rail items out of `page.tsx`. Add professor welcome messages and these exact personality options:

```ts
export const personalityOptions: Array<{
  id: PersonalityId;
  label: string;
  description: string;
}> = [
  { id: "default", label: "기본", description: "명확하고 중립적" },
  { id: "professional", label: "전문적", description: "정교하고 격식 있는 설명" },
  { id: "friendly", label: "친근함", description: "따뜻하고 대화하듯 설명" },
  { id: "candid", label: "솔직함", description: "핵심과 개선점을 직접 제시" },
  { id: "quirky", label: "개성 있음", description: "창의적인 비유와 가벼운 유머" },
  { id: "efficient", label: "효율적", description: "짧고 빠르게 핵심만 설명" },
  { id: "cynical", label: "냉소적", description: "건조한 유머와 실용적인 답변" }
];
```

Set `courseNavItems` to `홈`, `강의콘텐츠`, `출결현황`, `성적`, `AI 코스 에이전트`, with only the last item active.

- [ ] **Step 3: Run static verification**

Run: `npm run typecheck --workspace @skku-course-agent/frontend`
Expected: PASS with no TypeScript errors.

- [ ] **Step 4: Commit extracted assets and data**

```bash
git add apps/frontend/app/course-agent/ui-icon.tsx apps/frontend/app/course-agent/demo-data.ts
git commit -m "Extract iCampus course agent data"
```

### Task 3: Build role-specific controls

**Files:**
- Create: `apps/frontend/app/course-agent/role-controls.tsx`

**Interfaces:**
- Consumes: `CourseMaterial[]`, `CourseAgentState`, `CourseAgentAction`, personality options.
- Produces: `StudentControls`, `ProfessorControls`, `AttachmentList` React components.

- [ ] **Step 1: Implement shared attachment input and list**

Use a visually styled `<label>` backed by a hidden `<input type="file" multiple>`. On change, call `validateAttachment` for each file, create object URLs only for student images, dispatch `add-attachments`, and display the first validation error in `role="alert"`. Revoke image object URLs when removing an attachment and on component cleanup.

The shared props must be:

```ts
type AttachmentControlProps = {
  role: AgentRole;
  attachments: AttachmentItem[];
  dispatch: React.Dispatch<CourseAgentAction>;
};
```

- [ ] **Step 2: Implement student personality controls**

Render a labeled radio group from `personalityOptions`. Dispatch `set-personality` when changed. Below it render `AttachmentControl` with `accept=".pdf,.docx,.txt,.png,.jpg,.jpeg,image/png,image/jpeg"`.

- [ ] **Step 3: Implement professor material controls**

Render a checkbox for every material. Disable non-ready materials and include their processing status in visible text. `전체 선택` dispatches all ready material IDs; `전체 해제` dispatches an empty array. Below the list render `AttachmentControl` with `accept=".pdf,.pptx,.docx,.txt"`.

- [ ] **Step 4: Verify focused frontend quality**

Run: `npm run lint --workspace @skku-course-agent/frontend`
Expected: PASS with zero warnings.

Run: `npm run typecheck --workspace @skku-course-agent/frontend`
Expected: PASS.

- [ ] **Step 5: Commit role controls**

```bash
git add apps/frontend/app/course-agent/role-controls.tsx
git commit -m "Add student and professor agent controls"
```

### Task 4: Build the interactive iCampus course agent shell

**Files:**
- Create: `apps/frontend/app/course-agent/course-agent-demo.tsx`
- Modify: `apps/frontend/app/page.tsx`

**Interfaces:**
- Consumes: all exports from `demo-data.ts`, `courseAgentReducer`, `createInitialState`, `StudentControls`, `ProfessorControls`, `UiIcon`.
- Produces: default `CourseAgentDemo` client component and the `/` route UI.

- [ ] **Step 1: Create the client component state and persistence**

Start `course-agent-demo.tsx` with `"use client"`, `useReducer`, controlled question text, and submission state. Pass a reducer initializer that merges `studentInitialMessages` and `professorInitialMessages` into `createInitialState()` exactly once. Hydrate only serializable settings (`activeRole`, `student.personality`, `professor.selectedMaterialIds`) from `localStorage` key `skku-course-agent-settings-v1`; catch malformed storage and keep defaults. Persist those same settings after hydration. Do not persist `File`, object URLs, or message content.

- [ ] **Step 2: Render the iCampus shell**

Render these landmarks in order:

```tsx
<main className="icampus-shell">
  <aside className="global-navigation" aria-label="글로벌 내비게이션" />
  <div className="course-workspace">
    <header className="course-header" />
    <div className="course-layout">
      <aside className="course-navigation" aria-label="과목 탐색 메뉴" />
      <section className="agent-workspace" aria-labelledby="agent-title" />
    </div>
  </div>
</main>
```

The course header contains the hamburger button, exact visible course title `문제해결_SWE2026_41(조재민)`, and a `role-switch` group with two buttons. Each button uses `aria-pressed`, and dispatches `set-role`.

- [ ] **Step 3: Render role-independent chat**

Use the active role's independent messages. Render assistant citations immediately below their answer. Render insufficient responses with `data-insufficient="true"`. The composer contains attachment context chips, a controlled textarea, and a submit button disabled only when both text and active-role attachments are empty or while submitting.

On submit, append the user message immediately, then append a deterministic assistant demo response. Student responses include the chosen personality label and preserve citations. Professor responses name the selected and attached material counts. When professor RAG context is empty, return an insufficient-material message instead of inventing a sourced answer.

- [ ] **Step 4: Render role-specific right panel**

Within `agent-workspace`, use a two-column `agent-layout`. Put `StudentControls` or `ProfessorControls` in the right column based on `activeRole`. Keep the shared SAFE notice above both columns.

- [ ] **Step 5: Replace the route body**

Replace `page.tsx` with:

```tsx
import CourseAgentDemo from "./course-agent/course-agent-demo";

export default function Home() {
  return <CourseAgentDemo />;
}
```

- [ ] **Step 6: Verify behavior compiles**

Run: `npm run test --workspace @skku-course-agent/frontend`
Expected: PASS, 3 tests.

Run: `npm run typecheck --workspace @skku-course-agent/frontend`
Expected: PASS.

- [ ] **Step 7: Commit the interactive shell**

```bash
git add apps/frontend/app/page.tsx apps/frontend/app/course-agent/course-agent-demo.tsx
git commit -m "Build role-based iCampus agent shell"
```

### Task 5: Rebuild styling to match iCampus and remain responsive

**Files:**
- Modify: `apps/frontend/app/globals.css`

**Interfaces:**
- Consumes: class names from `course-agent-demo.tsx`, `role-controls.tsx`, and `ui-icon.tsx`.
- Produces: desktop iCampus visual match plus tablet and mobile layouts.

- [ ] **Step 1: Replace global tokens and desktop shell styles**

Use these root tokens:

```css
:root {
  color-scheme: light;
  --icampus-navy: #063b68;
  --icampus-navy-dark: #002f57;
  --icampus-teal: #0b6f7b;
  --icampus-course-nav: #f2f5fa;
  --icampus-border: #c7cdd3;
  --icampus-border-soft: #dfe3e7;
  --icampus-text: #2d3338;
  --icampus-muted: #5f676d;
  --icampus-surface: #ffffff;
  --icampus-canvas: #f7f8fa;
  --success: #287d3c;
  --warning: #9a6700;
  --danger: #b42318;
}
```

Set the desktop grid to `84px minmax(0, 1fr)`, the inner course grid to `220px minmax(0, 1fr)`, and the agent content grid to `minmax(480px, 1fr) 320px`. Match the reference with 1px rules, square-to-4px corners, no large shadows, 14–16px body text, and restrained padding.

- [ ] **Step 2: Style interaction states and accessibility**

Add visible `:focus-visible` outlines, active role and personality states that combine color, border, and text weight, disabled material rows with status text, image thumbnails, attachment chips, citation links, insufficient-answer warnings, and a sticky composer within the chat column. Respect `prefers-reduced-motion`.

- [ ] **Step 3: Add responsive layouts**

At `max-width: 1180px`, place role controls below chat. At `max-width: 860px`, make global navigation horizontal and scrollable, allow course navigation to become a compact horizontal/stacked section, and use a single content column. At `max-width: 560px`, stack the role switch and composer controls and keep all tap targets at least 40px tall.

- [ ] **Step 4: Run the full static verification**

Run: `npm run test --workspace @skku-course-agent/frontend`
Expected: PASS.

Run: `npm run lint`
Expected: PASS with zero warnings.

Run: `npm run typecheck`
Expected: PASS.

Run: `npm run build:frontend`
Expected: Next.js production build completes successfully and `/` is generated.

- [ ] **Step 5: Commit the visual redesign**

```bash
git add apps/frontend/app/globals.css
git commit -m "Match course agent to iCampus design"
```

### Task 6: Verify the complete experience in Chrome

**Files:**
- Modify only if verification reveals a defect: files from Tasks 1–5.

**Interfaces:**
- Consumes: local frontend at `http://localhost:3000` and the reference iCampus tab.
- Produces: verified responsive UI with no console errors and working role-specific interactions.

- [ ] **Step 1: Start the frontend**

Run: `npm run dev:frontend`
Expected: Next.js reports ready at `http://localhost:3000`.

- [ ] **Step 2: Compare desktop structure against iCampus**

Open the local page in Chrome at the same desktop viewport as the reference. Capture both screens and compare global navigation width/color, course navigation width/background, top-bar height, content density, borders, and alignment. Fix any visually material mismatch and repeat `npm run lint`, `npm run typecheck`, and `npm run build:frontend` after edits.

- [ ] **Step 3: Verify student flow**

In Chrome: select each of the seven personalities, attach one image and one allowed document, reject an invalid extension, send a question, confirm the answer and citation render, switch to professor, switch back, and confirm student settings remain intact. Inspect console logs and require zero errors.

- [ ] **Step 4: Verify professor flow**

In Chrome: confirm processing and failed materials are disabled, use select-all and clear-all, attach an allowed reference, reject an oversized/invalid file, chat with selected context, clear all context and confirm the next answer is visibly marked as insufficient. Switch roles twice and confirm professor state remains intact.

- [ ] **Step 5: Verify responsive and keyboard behavior**

Test 1180px, 860px, and 560px widths. Tab through the role switch, course navigation, material checkboxes, personality radios, attachment controls, removal buttons, textarea, and send button. Confirm focus is visible, labels are announced by DOM snapshot, and no horizontal content overflow hides the composer.

- [ ] **Step 6: Run final clean verification and commit fixes**

Run:

```bash
npm run test --workspace @skku-course-agent/frontend
npm run lint
npm run typecheck
npm run build:frontend
git diff --check
git status --short
```

Expected: all commands pass; `git diff --check` prints nothing; `git status --short` lists only intentional verification fixes, or nothing after the final commit.

If fixes were required:

```bash
git add apps/frontend
git commit -m "Polish iCampus agent interactions"
```
