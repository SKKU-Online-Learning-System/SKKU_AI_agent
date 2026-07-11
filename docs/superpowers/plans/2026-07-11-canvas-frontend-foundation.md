# Canvas Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive Canvas-like frontend foundation covering every required student, professor, and administrator screen in the PRD.

**Architecture:** Keep one shared Canvas shell and switch focused page components through a role-aware screen registry. Extend the existing reducer and demo data shapes so later API responses can replace local data without adding a speculative client layer.

**Tech Stack:** Next.js 16 App Router, React 18, TypeScript, CSS, Vitest, Testing Library

## Global Constraints

- Preserve the measured Canvas layout: 84px global rail, 220px secondary navigation, approximately 64px breadcrumb header.
- Reuse existing dependencies and shared domain types; add no new package.
- Keep the development-only student, professor, and administrator role switch.
- Keep RAG sources, material-insufficient messaging, SAFE learning guidance, upload validation, and role visibility explicit.
- Use Korean interface copy and accessible labels.

---

### Task 1: Role-aware navigation state

**Files:**
- Modify: `apps/frontend/app/course-agent/state.ts`
- Modify: `apps/frontend/app/course-agent/state.test.ts`
- Create: `apps/frontend/app/course-agent/navigation.ts`
- Create: `apps/frontend/app/course-agent/navigation.test.ts`

**Interfaces:**
- Produces: `AgentRole = "student" | "professor" | "admin"`, `ScreenId`, `roleNavigation`, `getDefaultScreen(role)`, reducer actions `set-role` and `set-screen`.
- Consumes: existing attachment, personality, message, and material-selection state.

- [ ] **Step 1: Write failing state and navigation tests**

```ts
it("moves each role to its default allowed screen", () => {
  const professor = courseAgentReducer(createInitialState(), {
    type: "set-role",
    role: "professor"
  });
  const admin = courseAgentReducer(professor, { type: "set-role", role: "admin" });
  expect(professor.activeScreen).toBe("professor-dashboard");
  expect(admin.activeScreen).toBe("admin-dashboard");
});

it("lists only screens allowed for a role", () => {
  expect(roleNavigation.student.map((item) => item.id)).toContain("student-chat");
  expect(roleNavigation.student.map((item) => item.id)).not.toContain("admin-users");
});
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `npm test --workspace @skku-course-agent/frontend -- state.test.ts navigation.test.ts`
Expected: FAIL because `admin`, `activeScreen`, and `roleNavigation` do not exist.

- [ ] **Step 3: Add minimal role navigation and reducer state**

```ts
export type AgentRole = "student" | "professor" | "admin";
export type ScreenId =
  | "student-login" | "student-courses" | "student-chat" | "student-history"
  | "professor-dashboard" | "professor-materials" | "professor-settings" | "professor-logs"
  | "admin-dashboard" | "admin-courses" | "admin-users" | "admin-materials" | "admin-logs";

export const getDefaultScreen = (role: AgentRole): ScreenId =>
  role === "student" ? "student-chat" : role === "professor" ? "professor-dashboard" : "admin-dashboard";
```

Add `activeScreen` to `CourseAgentState`; `set-role` sets both role and its default screen, while `set-screen` accepts a `ScreenId`.

- [ ] **Step 4: Run focused tests**

Run: `npm test --workspace @skku-course-agent/frontend -- state.test.ts navigation.test.ts`
Expected: PASS.

### Task 2: PRD demo data and reusable screen primitives

**Files:**
- Modify: `apps/frontend/app/course-agent/demo-data.ts`
- Modify: `apps/frontend/app/course-agent/demo-data.test.ts`
- Create: `apps/frontend/app/course-agent/screen-primitives.tsx`

**Interfaces:**
- Produces: `demoCourses`, `demoConversations`, `demoLogs`, `dashboardMetrics`, `StatusBadge`, `EmptyState`, `PageToolbar`, `MetricCard`.
- Consumes: shared `Course` and `CourseMaterial` types and `ScreenId`.

- [ ] **Step 1: Write failing fixture coverage test**

```ts
it("covers PRD states required by the role screens", () => {
  expect(demoCourses.some((course) => course.agentStatus === "inactive")).toBe(true);
  expect(materials.map((material) => material.status)).toEqual(
    expect.arrayContaining(["ready", "processing", "failed"])
  );
  expect(demoLogs[0]).toMatchObject({ role: expect.any(String), responseTime: expect.any(Number) });
  expect(dashboardMetrics.length).toBeGreaterThanOrEqual(5);
});
```

- [ ] **Step 2: Run fixture test and confirm failure**

Run: `npm test --workspace @skku-course-agent/frontend -- demo-data.test.ts`
Expected: FAIL because the new exports do not exist.

- [ ] **Step 3: Add typed fixtures and four small primitives**

Define local display types with exact fields used by screens: conversation `id, question, answer, createdAt`; log `id, role, course, user, question, source, model, responseTime, createdAt`; metric `label, value, detail`. Primitives accept children and standard form props only; they contain no fetching or business logic.

- [ ] **Step 4: Run fixture test**

Run: `npm test --workspace @skku-course-agent/frontend -- demo-data.test.ts`
Expected: PASS.

### Task 3: Student, professor, and administrator screens

**Files:**
- Create: `apps/frontend/app/course-agent/student-screens.tsx`
- Create: `apps/frontend/app/course-agent/professor-screens.tsx`
- Create: `apps/frontend/app/course-agent/admin-screens.tsx`
- Create: `apps/frontend/app/course-agent/screens.test.tsx`

**Interfaces:**
- Produces: `StudentScreen`, `ProfessorScreen`, `AdminScreen` components taking `screen`, data, and narrow callback props.
- Consumes: demo fixtures, primitives, existing `StudentControls`, `ProfessorControls`, message and material state.

- [ ] **Step 1: Write failing role-screen tests**

```tsx
it("renders source and insufficiency guidance in student chat", () => {
  render(<StudentScreen screen="student-chat" />);
  expect(screen.getByText(/2주차 RAG 개요/)).toBeInTheDocument();
  expect(screen.getByText(/AI 답변은 학습 보조용/)).toBeInTheDocument();
});

it("renders professor material processing states", () => {
  render(<ProfessorScreen screen="professor-materials" />);
  expect(screen.getByText("처리 중")).toBeInTheDocument();
  expect(screen.getByText("실패")).toBeInTheDocument();
});

it("filters administrator users by role", () => {
  render(<AdminScreen screen="admin-users" />);
  fireEvent.change(screen.getByLabelText("역할 필터"), { target: { value: "professor" } });
  expect(screen.getByText("김교수")).toBeInTheDocument();
  expect(screen.queryByText("박학생")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run screen tests and confirm failure**

Run: `npm test --workspace @skku-course-agent/frontend -- screens.test.tsx`
Expected: FAIL because role screen components do not exist.

- [ ] **Step 3: Implement minimal interactive role screens**

Student screens render login actions, active/inactive course cards, existing chat interaction, and selectable conversation history. Professor screens render metrics, upload/status rows, agent/policy controls, and searchable logs. Administrator screens render metrics, editable course state, role-filtered users, material actions, and filtered audit logs. Server mutations update local component or reducer state and show an `aria-live` confirmation.

- [ ] **Step 4: Run screen tests**

Run: `npm test --workspace @skku-course-agent/frontend -- screens.test.tsx`
Expected: PASS.

### Task 4: Canvas shell integration and responsive styling

**Files:**
- Modify: `apps/frontend/app/course-agent/course-agent-demo.tsx`
- Modify: `apps/frontend/app/course-agent/course-agent-demo.test.tsx`
- Modify: `apps/frontend/app/globals.css`

**Interfaces:**
- Produces: role-aware Canvas shell with working global rail, secondary menu, breadcrumbs, role switch, screen registry, and mobile drawer.
- Consumes: `roleNavigation`, reducer state/actions, and three role-screen components.

- [ ] **Step 1: Extend integration tests**

```tsx
it("navigates every role through its allowed Canvas menu", () => {
  render(<CourseAgentDemo />);
  fireEvent.click(screen.getByRole("button", { name: "관리자" }));
  fireEvent.click(screen.getByRole("button", { name: "사용자 및 권한" }));
  expect(screen.getByRole("heading", { name: "사용자 및 권한" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "최근 대화" })).not.toBeInTheDocument();
});

it("exposes the mobile navigation toggle", () => {
  render(<CourseAgentDemo />);
  const toggle = screen.getByRole("button", { name: "과목 메뉴 열기" });
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
});
```

- [ ] **Step 2: Run integration tests and confirm failure**

Run: `npm test --workspace @skku-course-agent/frontend -- course-agent-demo.test.tsx`
Expected: FAIL because administrator navigation and mobile drawer do not exist.

- [ ] **Step 3: Integrate shell and CSS**

Replace hard-coded course menu buttons with `roleNavigation[state.activeRole]`; render the matching role screen; keep the 84px/220px/64px desktop geometry. Add CSS breakpoints at 900px and 640px to collapse the rail and turn the secondary menu into a controlled drawer. Preserve focus outlines, `aria-current`, 44px touch targets, Canvas colors, thin borders, and existing chat states.

- [ ] **Step 4: Run all frontend tests**

Run: `npm test --workspace @skku-course-agent/frontend`
Expected: all Vitest tests PASS.

### Task 5: Full verification

**Files:**
- Modify only files required by failures found during verification.

**Interfaces:**
- Produces: verified frontend build.
- Consumes: all prior tasks.

- [ ] **Step 1: Run static checks**

Run: `npm run lint`
Expected: exit 0, no warnings.

Run: `npm run typecheck`
Expected: exit 0.

- [ ] **Step 2: Run production build**

Run: `npm run build:frontend`
Expected: Next.js production build succeeds.

- [ ] **Step 3: Run browser verification**

Start: `npm run dev:frontend`

Verify at `http://localhost:3000`: student, professor, administrator role switching; every secondary menu target; chat submission; source and insufficient states; upload validation; policy and active-state toggles; search and role filters; 1920px desktop geometry; 900px and 640px responsive navigation.

- [ ] **Step 4: Inspect final diff**

Run: `git diff --check`
Expected: exit 0.

Run: `git status --short`
Expected: only intended frontend, test, and plan files plus the untracked `.superpowers/` companion artifact.
