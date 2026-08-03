# Course-First Role Dashboards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace role action-card home pages with the existing role-appropriate course list and management screens.

**Architecture:** Keep course loading, filtering, errors, and authorization inside the existing `CourseListClient` and `AdminCoursesClient`. The three role home pages become thin route adapters that render those existing clients; the obsolete `RoleDashboard` component and its CSS are removed after the new route behavior passes tests.

**Tech Stack:** Next.js 16 App Router, React 18, TypeScript, Vitest, Testing Library, CSS

## Global Constraints

- Preserve the existing i-Campus shell, role navigation, login, JWT, and `ProtectedRoute` boundaries.
- Keep `/student/courses`, `/professor/courses`, and `/admin/courses` working as existing feature routes.
- Add no API calls, dependencies, fallback data, or duplicated course-list implementations.
- Student home shows active accessible courses; professor home shows assigned courses; admin home keeps the full searchable and editable course management screen.
- Use TDD: observe the route tests fail before changing production pages.
- Preserve the user-owned `apps/frontend/next-env.d.ts` change and untracked `.superpowers/` directory.

## File Map

- Create `apps/frontend/app/dashboard-pages.test.tsx`: verifies which existing course client each role home renders.
- Modify `apps/frontend/app/student/page.tsx`: renders student `CourseListClient`.
- Modify `apps/frontend/app/professor/page.tsx`: renders professor `CourseListClient`.
- Modify `apps/frontend/app/admin/page.tsx`: renders `AdminCoursesClient`.
- Delete `apps/frontend/app/components/dashboard/role-dashboard.tsx`: obsolete action-card dashboard.
- Delete `apps/frontend/app/components/dashboard/role-dashboard.test.tsx`: obsolete component test.
- Modify `apps/frontend/app/globals.css`: removes only `.role-dashboard*` rules; retains `.role-page*` rules used by users, materials, and chat placeholder pages.

---

### Task 1: Render Courses on Every Role Home

**Files:**
- Create: `apps/frontend/app/dashboard-pages.test.tsx`
- Modify: `apps/frontend/app/student/page.tsx`
- Modify: `apps/frontend/app/professor/page.tsx`
- Modify: `apps/frontend/app/admin/page.tsx`
- Delete: `apps/frontend/app/components/dashboard/role-dashboard.tsx`
- Delete: `apps/frontend/app/components/dashboard/role-dashboard.test.tsx`
- Modify: `apps/frontend/app/globals.css:360-408`
- Test: `apps/frontend/app/dashboard-pages.test.tsx`

**Interfaces:**
- Consumes: `CourseListClient({ audience }: { audience: "professor" | "student" })` from `apps/frontend/app/components/courses/course-list-client.tsx`.
- Consumes: `AdminCoursesClient()` from `apps/frontend/app/admin/courses/admin-courses-client.tsx`.
- Produces: role home route components that delegate to the existing course clients without changing their props or data flow.

- [ ] **Step 1: Write the failing role-home tests**

Create `apps/frontend/app/dashboard-pages.test.tsx`:

```tsx
// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdminDashboardPage from "./admin/page";
import ProfessorDashboardPage from "./professor/page";
import StudentDashboardPage from "./student/page";

vi.mock("./components/courses/course-list-client", () => ({
  CourseListClient: ({ audience }: { audience: "professor" | "student" }) => (
    <div data-testid={`course-list-${audience}`} />
  )
}));

vi.mock("./admin/courses/admin-courses-client", () => ({
  AdminCoursesClient: () => <div data-testid="admin-course-management" />
}));

afterEach(cleanup);

describe("role dashboard pages", () => {
  it("shows the student's accessible courses", () => {
    render(<StudentDashboardPage />);
    expect(screen.getByTestId("course-list-student")).toBeInTheDocument();
  });

  it("shows the professor's assigned courses", () => {
    render(<ProfessorDashboardPage />);
    expect(screen.getByTestId("course-list-professor")).toBeInTheDocument();
  });

  it("shows full course management for the administrator", () => {
    render(<AdminDashboardPage />);
    expect(screen.getByTestId("admin-course-management")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/dashboard-pages.test.tsx
```

Expected: three failures because the current home pages render `RoleDashboard` action links instead of the mocked course clients.

- [ ] **Step 3: Replace the student home with the existing student course list**

Replace `apps/frontend/app/student/page.tsx` with:

```tsx
import { CourseListClient } from "../components/courses/course-list-client";

export default function StudentDashboardPage() {
  return <CourseListClient audience="student" />;
}
```

- [ ] **Step 4: Replace the professor home with the existing professor course list**

Replace `apps/frontend/app/professor/page.tsx` with:

```tsx
import { CourseListClient } from "../components/courses/course-list-client";

export default function ProfessorDashboardPage() {
  return <CourseListClient audience="professor" />;
}
```

- [ ] **Step 5: Replace the admin home with full course management**

Replace `apps/frontend/app/admin/page.tsx` with:

```tsx
import { AdminCoursesClient } from "./courses/admin-courses-client";

export default function AdminDashboardPage() {
  return <AdminCoursesClient />;
}
```

- [ ] **Step 6: Run the focused test and verify GREEN**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/dashboard-pages.test.tsx
```

Expected: one test file and all three tests pass.

- [ ] **Step 7: Remove the obsolete action-card dashboard**

Delete these files:

```text
apps/frontend/app/components/dashboard/role-dashboard.tsx
apps/frontend/app/components/dashboard/role-dashboard.test.tsx
```

Remove the complete CSS block from `.role-dashboard {` through the closing brace of `.role-dashboard-card-body` in `apps/frontend/app/globals.css`. Do not remove `.role-page`, `.role-page-grid`, or their descendants because `/admin/users`, `/admin/materials`, and `/student/chat` still use them.

- [ ] **Step 8: Run the frontend regression suite**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend
```

Expected: 13 test files and 55 tests pass: the obsolete one-test file is removed and the new three-test file is added to the previous 53-test baseline.

- [ ] **Step 9: Run static verification and production build**

Run each command:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build:frontend
git diff --check
```

Expected: every command exits 0. If the production build rewrites `apps/frontend/next-env.d.ts`, restore its pre-task contents and verify that the file has no task-related diff.

- [ ] **Step 10: Verify the three dashboards with the seeded local stack**

Start the existing PostgreSQL, API, and frontend using the repository commands:

```powershell
docker compose up -d db
Set-Location apps/backend
py -m alembic upgrade head
py -m app.db.seed
Set-Location ../..
py -m uvicorn app.main:app --app-dir apps/backend --host 127.0.0.1 --port 8000
npm.cmd run dev:frontend
```

In Chrome, verify:

```text
student@skku.edu / password123 -> /student -> heading "내 과목" and seeded course rows
professor@skku.edu / password123 -> /professor -> heading "담당 과목" and assigned course rows
admin@skku.edu / password123 -> /admin -> heading "과목 관리", filters, "새 과목", and course action controls
```

Also verify that the left navigation, local SKKU logo, mobile menu toggle, logout, and the existing `/student/courses`, `/professor/courses`, `/admin/courses` routes still work. Stop only the API and frontend processes started for this verification.

- [ ] **Step 11: Commit the implementation**

Stage only the task files and commit:

```powershell
git add -- apps/frontend/app/dashboard-pages.test.tsx apps/frontend/app/student/page.tsx apps/frontend/app/professor/page.tsx apps/frontend/app/admin/page.tsx apps/frontend/app/components/dashboard/role-dashboard.tsx apps/frontend/app/components/dashboard/role-dashboard.test.tsx apps/frontend/app/globals.css
git commit -m "Show courses on role dashboards"
```
