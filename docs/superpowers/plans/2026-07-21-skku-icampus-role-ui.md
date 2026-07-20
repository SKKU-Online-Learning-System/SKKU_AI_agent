# SKKU i-Campus Role UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the login and authenticated student, professor, and administrator surfaces with the approved SKKU i-Campus visual structure while preserving the existing auth, role, API, and course-agent behavior.

**Architecture:** Keep `AuthProvider`, `ProtectedRoute`, role routes, and API clients as the behavioral boundary. Extend the existing role menu model with icon metadata, rebuild `AppShell` from focused global-navigation, context-navigation, and topbar components, and reuse one Canvas-style course-card component for student and professor data. Keep administrator forms and tables intact inside the new shell and apply shared i-Campus tokens through `globals.css`.

**Tech Stack:** Next.js 16 App Router, React 18, TypeScript 5.5, CSS, Vitest 3, Testing Library, existing REST API client.

## Global Constraints

- Preserve the existing email/password request, JWT storage, role routing, protected routes, and backend permission checks.
- Use `#003669` for the 84px global navigation and `#f3f6fb` for the 220px context navigation.
- Use local SKKU assets at runtime; do not depend on an external logo URL.
- Reuse a single 24x24 SVG line-icon system; do not add separate bitmap files for menu icons.
- Show only product routes that work today; do not add decorative Canvas links with no implementation.
- Keep the existing course-agent SAFE notice, source display, material-insufficient state, attachments, and professor/student controls.
- Use Windows-safe commands: `npm.cmd`, not `npm`.
- Preserve unrelated working-tree changes, especially `apps/frontend/next-env.d.ts`.

---

## File Map

- Create `apps/frontend/app/components/ui/ui-icon.tsx`: shared typed SVG icon renderer.
- Create `apps/frontend/app/components/auth/app-shell.test.tsx`: global and context navigation behavior.
- Create `apps/frontend/app/login/page.test.tsx`: i-Campus login structure and preserved submission behavior.
- Create `apps/frontend/app/components/dashboard/role-dashboard.tsx`: Canvas-style role landing layout.
- Create `apps/frontend/app/components/dashboard/role-dashboard.test.tsx`: role landing link and icon coverage.
- Create `apps/frontend/public/icampus-login-logo.png`: local official horizontal login logo.
- Modify `apps/frontend/app/lib/auth.ts`: typed global/context navigation definitions.
- Modify `apps/frontend/app/lib/auth.test.ts`: exact role menu and icon expectations.
- Modify `apps/frontend/app/components/auth/app-shell.tsx`: compose the three-part authenticated shell.
- Modify `apps/frontend/app/login/page.tsx`: official i-Campus login markup.
- Modify `apps/frontend/app/admin/page.tsx`: administrator role dashboard.
- Modify `apps/frontend/app/professor/page.tsx`: professor role dashboard.
- Modify `apps/frontend/app/student/page.tsx`: student role dashboard.
- Modify `apps/frontend/app/globals.css`: shared tokens, login, shell, dashboards, existing forms/tables, and responsive rules.

### Task 1: Promote the SVG Icon System and Type Role Navigation

**Files:**
- Create: `apps/frontend/app/components/ui/ui-icon.tsx`
- Modify: `apps/frontend/app/lib/auth.ts`
- Modify: `apps/frontend/app/lib/auth.test.ts`

**Interfaces:**
- Produces: shared re-exports of `IconName` and `UiIcon({ name, className })`, `RoleMenuItem.icon`, `getRoleMenuItems(role)`.
- Consumes: `UserRole` from `@skku-course-agent/shared`.

- [ ] **Step 1: Extend the auth policy test with exact labels, paths, and icons**

Replace the menu assertion in `app/lib/auth.test.ts` with:

```ts
expect(getRoleMenuItems("admin")).toEqual([
  { href: "/admin", label: "대시보드", icon: "dashboard" },
  { href: "/admin/courses", label: "과목", icon: "course" },
  { href: "/admin/users", label: "사용자", icon: "group" },
  { href: "/admin/materials", label: "자료", icon: "material" }
]);
expect(getRoleMenuItems("professor")).toEqual([
  { href: "/professor", label: "대시보드", icon: "dashboard" },
  { href: "/professor/courses", label: "담당 과목", icon: "course" },
  { href: "/professor/materials", label: "강의자료", icon: "material" }
]);
expect(getRoleMenuItems("student")).toEqual([
  { href: "/student", label: "대시보드", icon: "dashboard" },
  { href: "/student/courses", label: "내 과목", icon: "course" },
  { href: "/student/chat", label: "AI 질문", icon: "agent" }
]);
```

- [ ] **Step 2: Run the focused test and confirm the new contract fails**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/lib/auth.test.ts
```

Expected: FAIL because menu objects do not contain the approved labels and `icon`.

- [ ] **Step 3: Create the shared icon entrypoint**

Keep the tested SVG implementation in `course-agent/ui-icon.tsx` and expose the
same renderer to auth and dashboard components through
`components/ui/ui-icon.tsx`:

```tsx
export { UiIcon } from "../../course-agent/ui-icon";
export type { IconName } from "../../course-agent/ui-icon";
```

- [ ] **Step 4: Add icon metadata to the role menu model**

Change `RoleMenuItem` and `roleMenuItems` in `lib/auth.ts`:

```ts
import type { IconName } from "../components/ui/ui-icon";

export type RoleMenuItem = {
  href: string;
  label: string;
  icon: IconName;
};

const roleMenuItems: Record<UserRole, RoleMenuItem[]> = {
  admin: [
    { href: "/admin", label: "대시보드", icon: "dashboard" },
    { href: "/admin/courses", label: "과목", icon: "course" },
    { href: "/admin/users", label: "사용자", icon: "group" },
    { href: "/admin/materials", label: "자료", icon: "material" }
  ],
  professor: [
    { href: "/professor", label: "대시보드", icon: "dashboard" },
    { href: "/professor/courses", label: "담당 과목", icon: "course" },
    { href: "/professor/materials", label: "강의자료", icon: "material" }
  ],
  student: [
    { href: "/student", label: "대시보드", icon: "dashboard" },
    { href: "/student/courses", label: "내 과목", icon: "course" },
    { href: "/student/chat", label: "AI 질문", icon: "agent" }
  ]
};
```

- [ ] **Step 5: Run icon-dependent and auth tests**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/lib/auth.test.ts app/course-agent/course-agent-demo.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit the typed navigation boundary**

```powershell
git add -- apps/frontend/app/components/ui/ui-icon.tsx apps/frontend/app/lib/auth.ts apps/frontend/app/lib/auth.test.ts
git commit -m "Add i-Campus navigation icons"
```

### Task 2: Rebuild the Authenticated i-Campus Shell

**Files:**
- Create: `apps/frontend/app/components/auth/app-shell.test.tsx`
- Modify: `apps/frontend/app/components/auth/app-shell.tsx`
- Modify: `apps/frontend/app/globals.css`

**Interfaces:**
- Consumes: `UiIcon`, `getRoleHomePath`, `getRoleMenuItems`, `roleLabels`, and `useAuth`.
- Produces: `AppShell({ children })` with global navigation, context navigation, topbar, and logout behavior.

- [ ] **Step 1: Write shell behavior tests**

Create `components/auth/app-shell.test.tsx` with navigation and logout coverage:

```tsx
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./app-shell";

const mocks = vi.hoisted(() => ({
  pathname: { value: "/student/courses" },
  replace: vi.fn(),
  logout: vi.fn()
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname.value,
  useRouter: () => ({ replace: mocks.replace })
}));

vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    logout: mocks.logout,
    user: {
      id: "student-1",
      name: "Student",
      email: "student@skku.edu",
      role: "student"
    }
  })
}));

afterEach(() => {
  cleanup();
  mocks.logout.mockClear();
  mocks.replace.mockClear();
});

describe("AppShell", () => {
  it("renders SKKU branding, global icons, and the active context link", () => {
    render(<AppShell><p>Course content</p></AppShell>);

    expect(screen.getByAltText("성균관대학교")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "글로벌 내비게이션" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "학생 메뉴" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "내 과목" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Course content")).toBeInTheDocument();
  });

  it("logs out and returns to login", () => {
    render(<AppShell><p>Content</p></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
    expect(mocks.logout).toHaveBeenCalledTimes(1);
    expect(mocks.replace).toHaveBeenCalledWith("/login");
  });
});
```

- [ ] **Step 2: Run the test and verify it fails against the old shell**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/components/auth/app-shell.test.tsx
```

Expected: FAIL because the old shell has no SKKU image, global navigation, or named context navigation.

- [ ] **Step 3: Replace the shell markup**

Refactor `app-shell.tsx` around this exact structure:

```tsx
<div className="icampus-app-shell">
  <aside className="icampus-global-nav">
    <Link className="icampus-crest" href={roleHomePath}>
      <img alt="성균관대학교" src="/skku-logo-white.PNG" />
    </Link>
    <nav aria-label="글로벌 내비게이션">
      {menuItems.map((item) => (
        <Link
          aria-current={isActivePath(pathname, item.href, roleHomePath) ? "page" : undefined}
          href={item.href}
          key={item.href}
        >
          <UiIcon name={item.icon} />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  </aside>
  <aside className="icampus-context-nav">
    <strong>{roleLabels[user.role]} 메뉴</strong>
    <nav aria-label={`${roleLabels[user.role]} 메뉴`}>
      {menuItems.map((item) => (
        <Link
          aria-current={isActivePath(pathname, item.href, roleHomePath) ? "page" : undefined}
          href={item.href}
          key={item.href}
        >
          <UiIcon name={item.icon} />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  </aside>
  <div className="icampus-app-main">
    <header className="icampus-app-topbar">
      <span className="icampus-menu-mark" aria-hidden="true">☰</span>
      <strong>{roleLabels[user.role]} 대시보드</strong>
      <div className="icampus-user-menu">
        <span>{user.name}</span>
        <button type="button" onClick={handleLogout}>로그아웃</button>
      </div>
    </header>
    <main className="icampus-app-content">{children}</main>
  </div>
</div>
```

Implement:

```ts
function isActivePath(pathname: string, href: string, roleHomePath: string): boolean {
  return href === roleHomePath
    ? pathname === href
    : pathname === href || pathname.startsWith(`${href}/`);
}
```

- [ ] **Step 4: Add the shell tokens and responsive CSS**

Add focused rules to `globals.css`:

```css
:root {
  --icampus-navy: #003669;
  --icampus-course-nav: #f3f6fb;
  --icampus-border: #c7cdd3;
  --icampus-text: #434343;
}

.icampus-app-shell {
  display: grid;
  grid-template-columns: 84px 220px minmax(0, 1fr);
  min-height: 100vh;
}

.icampus-global-nav {
  background: var(--icampus-navy);
  color: white;
}

.icampus-global-nav nav a {
  align-items: center;
  color: white;
  display: grid;
  font-size: 13px;
  gap: 4px;
  justify-items: center;
  min-height: 72px;
  padding: 8px 3px;
  text-decoration: none;
}

.icampus-global-nav nav a[aria-current="page"] {
  background: white;
  color: var(--icampus-navy);
}

.icampus-context-nav {
  background: var(--icampus-course-nav);
  padding: 28px 12px;
}

.icampus-context-nav nav a {
  align-items: center;
  border: 1px solid transparent;
  border-radius: 4px;
  color: var(--icampus-text);
  display: flex;
  gap: 9px;
  min-height: 40px;
  padding: 8px 10px;
  text-decoration: none;
}

.icampus-context-nav nav a[aria-current="page"] {
  background: white;
  border-color: #12649b;
  color: var(--icampus-navy);
  font-weight: 700;
}

.icampus-app-topbar {
  align-items: center;
  background: white;
  border-bottom: 1px solid var(--icampus-border);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  min-height: 72px;
  padding: 0 24px;
}

@media (max-width: 860px) {
  .icampus-app-shell {
    display: block;
  }

  .icampus-global-nav nav {
    display: flex;
    overflow-x: auto;
  }

  .icampus-context-nav {
    overflow-x: auto;
    padding: 10px;
  }

  .icampus-context-nav nav {
    display: flex;
    width: max-content;
  }
}
```

Remove the old `.app-shell`, `.app-sidebar`, `.app-topbar`, and related mobile rules after all replacements compile.

- [ ] **Step 5: Run shell and route policy tests**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/components/auth/app-shell.test.tsx app/components/auth/protected-route.test.tsx app/lib/auth.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit the authenticated shell**

```powershell
git add -- apps/frontend/app/components/auth/app-shell.tsx apps/frontend/app/components/auth/app-shell.test.tsx apps/frontend/app/globals.css
git commit -m "Build i-Campus app shell"
```

### Task 3: Recreate the Official-Style Login Without Changing Auth

**Files:**
- Create: `apps/frontend/app/login/page.test.tsx`
- Create: `apps/frontend/public/icampus-login-logo.png`
- Modify: `apps/frontend/app/login/page.tsx`
- Modify: `apps/frontend/app/globals.css`

**Interfaces:**
- Consumes: `useAuth().login(email, password)`, `ApiError`, and `getRoleHomePath`.
- Produces: the approved i-Campus login markup with a local logo.

- [ ] **Step 1: Write login behavior and visual-contract tests**

Create `login/page.test.tsx`:

```tsx
// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./page";

const mocks = vi.hoisted(() => ({
  login: vi.fn(),
  replace: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace })
}));

vi.mock("../components/auth/auth-provider", () => ({
  useAuth: () => ({
    login: mocks.login,
    status: "unauthenticated",
    user: null
  })
}));

afterEach(() => {
  cleanup();
  mocks.login.mockReset();
  mocks.replace.mockReset();
});

describe("LoginPage", () => {
  it("renders the local i-Campus brand and accessible credentials", () => {
    render(<LoginPage />);
    expect(screen.getByAltText("성균관대학교 i-Campus")).toHaveAttribute(
      "src",
      "/icampus-login-logo.png"
    );
    expect(screen.getByLabelText("아이디 또는 이메일")).toBeInTheDocument();
    expect(screen.getByLabelText("비밀번호")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "LOGIN" })).toBeInTheDocument();
  });

  it("uses the existing login contract and redirects by role", async () => {
    mocks.login.mockResolvedValue({
      id: "student-1",
      name: "Student",
      email: "student@skku.edu",
      role: "student"
    });
    render(<LoginPage />);
    fireEvent.change(screen.getByLabelText("아이디 또는 이메일"), {
      target: { value: "student@skku.edu" }
    });
    fireEvent.change(screen.getByLabelText("비밀번호"), {
      target: { value: "password123" }
    });
    fireEvent.click(screen.getByRole("button", { name: "LOGIN" }));
    await waitFor(() => {
      expect(mocks.login).toHaveBeenCalledWith("student@skku.edu", "password123");
      expect(mocks.replace).toHaveBeenCalledWith("/student");
    });
  });
});
```

- [ ] **Step 2: Verify the tests fail against the old login**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/login/page.test.tsx
```

Expected: FAIL because the old page has no local i-Campus logo, approved label, or `LOGIN` button text.

- [ ] **Step 3: Download the official public horizontal logo as a local asset**

Run:

```powershell
Invoke-WebRequest -Uri "https://icampus.skku.edu/xn-sso/customs/resources/image/logo.png?v=4" -OutFile "apps/frontend/public/icampus-login-logo.png"
```

Verify:

```powershell
Get-Item "apps/frontend/public/icampus-login-logo.png" | Select-Object Length
```

Expected: a non-zero PNG file.

- [ ] **Step 4: Replace only the login markup**

Keep `handleSubmit` and the authenticated redirect effect unchanged. Replace the returned JSX with:

```tsx
<main className="icampus-login-page">
  <section className="icampus-login" aria-labelledby="login-title">
    <h1 id="login-title">
      <img alt="성균관대학교 i-Campus" src="/icampus-login-logo.png" />
    </h1>
    <form onSubmit={handleSubmit}>
      <label>
        <span>아이디 또는 이메일</span>
        <input
          autoComplete="username"
          name="email"
          onChange={(event) => setEmail(event.target.value)}
          placeholder="ID"
          required
          type="email"
          value={email}
        />
      </label>
      <label>
        <span>비밀번호</span>
        <input
          autoComplete="current-password"
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Password"
          required
          type="password"
          value={password}
        />
      </label>
      {errorMessage ? <p role="alert">{errorMessage}</p> : null}
      <button disabled={isSubmitting || status === "loading"} type="submit">
        {isSubmitting ? "LOGIN..." : "LOGIN"}
      </button>
    </form>
    <p className="icampus-login-help">
      성균관대학교 강의자료 기반 AI 코스 에이전트입니다.
    </p>
  </section>
</main>
```

- [ ] **Step 5: Add the approved login styles**

Use flat white layout rules:

```css
.icampus-login-page {
  background: white;
  min-height: 100vh;
  padding: 96px 24px 40px;
}

.icampus-login {
  margin: 0 auto;
  max-width: 600px;
}

.icampus-login h1 {
  border-bottom: 1px solid #d9d9d9;
  margin: 0 0 48px;
  padding: 24px 0;
}

.icampus-login h1 img {
  display: block;
  height: auto;
  width: 283px;
}

.icampus-login form {
  margin: 0 auto;
  max-width: 400px;
}

.icampus-login label {
  display: block;
}

.icampus-login label span {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.icampus-login input {
  border: 1px solid #dedede;
  min-height: 58px;
  padding: 0 18px;
  width: 100%;
}

.icampus-login label + label input {
  border-top: 0;
}

.icampus-login button {
  background: #4e8e0d;
  border: 0;
  color: white;
  font-size: 22px;
  font-weight: 800;
  min-height: 65px;
  margin-top: 20px;
  width: 100%;
}
```

Delete the superseded `.login-page` and `.login-panel` rules.

- [ ] **Step 6: Run login and API regression tests**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/login/page.test.tsx app/lib/api.test.ts
```

Expected: PASS, including the existing response-less network failure case.

- [ ] **Step 7: Commit the login redesign**

```powershell
git add -- apps/frontend/app/login/page.tsx apps/frontend/app/login/page.test.tsx apps/frontend/app/globals.css apps/frontend/public/icampus-login-logo.png
git commit -m "Match i-Campus login design"
```

### Task 4: Add Separate Student, Professor, and Admin Dashboards

**Files:**
- Create: `apps/frontend/app/components/dashboard/role-dashboard.tsx`
- Create: `apps/frontend/app/components/dashboard/role-dashboard.test.tsx`
- Modify: `apps/frontend/app/student/page.tsx`
- Modify: `apps/frontend/app/professor/page.tsx`
- Modify: `apps/frontend/app/admin/page.tsx`
- Modify: `apps/frontend/app/globals.css`
- Delete: `apps/frontend/app/components/auth/role-page.tsx`

**Interfaces:**
- Produces: `DashboardAction`, `RoleDashboard({ title, description, actions })`.
- Consumes: `IconName`, `UiIcon`, and working role routes.

- [ ] **Step 1: Write a reusable dashboard test**

Create `components/dashboard/role-dashboard.test.tsx`:

```tsx
// @vitest-environment jsdom

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { RoleDashboard } from "./role-dashboard";

describe("RoleDashboard", () => {
  it("renders Canvas-style action cards as real links", () => {
    render(
      <RoleDashboard
        actions={[
          {
            description: "수강 과목을 확인합니다.",
            href: "/student/courses",
            icon: "course",
            label: "내 과목"
          }
        ]}
        description="학생 학습 화면입니다."
        title="대시보드"
      />
    );
    expect(screen.getByRole("heading", { name: "대시보드" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /내 과목/ })).toHaveAttribute(
      "href",
      "/student/courses"
    );
    expect(screen.getByText("수강 과목을 확인합니다.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the new test and confirm the component is missing**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/components/dashboard/role-dashboard.test.tsx
```

Expected: FAIL because `role-dashboard.tsx` does not exist.

- [ ] **Step 3: Implement the reusable dashboard**

Create:

```tsx
import Link from "next/link";
import type { IconName } from "../ui/ui-icon";
import { UiIcon } from "../ui/ui-icon";

export type DashboardAction = {
  description: string;
  href: string;
  icon: IconName;
  label: string;
};

export function RoleDashboard({
  actions,
  description,
  title
}: {
  actions: DashboardAction[];
  description: string;
  title: string;
}) {
  return (
    <section className="role-dashboard">
      <header>
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <div className="role-dashboard-grid">
        {actions.map((action, index) => (
          <Link href={action.href} key={action.href}>
            <span className="role-dashboard-card-color" data-color={index % 4} />
            <span className="role-dashboard-card-body">
              <UiIcon name={action.icon} />
              <strong>{action.label}</strong>
              <small>{action.description}</small>
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Replace placeholder role pages with approved actions**

Use these exact arrays:

```tsx
// student/page.tsx
[
  { href: "/student/courses", label: "내 과목", description: "수강 가능한 활성 과목을 확인합니다.", icon: "course" },
  { href: "/student/chat", label: "AI 질문", description: "강의자료를 근거로 질문하고 출처를 확인합니다.", icon: "agent" }
]

// professor/page.tsx
[
  { href: "/professor/courses", label: "담당 과목", description: "담당 과목과 에이전트 상태를 확인합니다.", icon: "course" },
  { href: "/professor/materials", label: "강의자료", description: "자료를 업로드하고 처리 상태를 확인합니다.", icon: "material" }
]

// admin/page.tsx
[
  { href: "/admin/courses", label: "과목 관리", description: "과목을 등록하고 활성 상태를 관리합니다.", icon: "course" },
  { href: "/admin/users", label: "사용자 관리", description: "사용자 역할과 접근 권한을 확인합니다.", icon: "group" },
  { href: "/admin/materials", label: "자료 관리", description: "전체 자료와 처리 상태를 확인합니다.", icon: "material" }
]
```

Pass `title="대시보드"` and role-specific descriptions to `RoleDashboard`.

- [ ] **Step 5: Add Canvas dashboard card styles**

Add:

```css
.role-dashboard {
  display: grid;
  gap: 24px;
}

.role-dashboard > header {
  border-bottom: 1px solid var(--icampus-border);
  display: grid;
  gap: 8px;
  padding-bottom: 16px;
}

.role-dashboard-grid {
  display: grid;
  gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(240px, 280px));
}

.role-dashboard-grid > a {
  background: white;
  border-radius: 4px;
  box-shadow: 0 2px 5px rgba(0, 0, 0, 0.3);
  color: var(--icampus-text);
  overflow: hidden;
  text-decoration: none;
}

.role-dashboard-card-color {
  background: #16836f;
  display: block;
  height: 116px;
}

.role-dashboard-card-color[data-color="1"] {
  background: #a87919;
}

.role-dashboard-card-color[data-color="2"] {
  background: #6f8886;
}

.role-dashboard-card-body {
  display: grid;
  gap: 7px;
  min-height: 132px;
  padding: 16px;
}
```

Remove `role-page` usage from the three role home pages and delete
`components/auth/role-page.tsx`; the current repository has no other consumers.

- [ ] **Step 6: Run dashboard and page-adjacent tests**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend -- app/components/dashboard/role-dashboard.test.tsx app/components/courses/course-list-client.test.tsx app/admin/courses/admin-courses-client.test.tsx app/professor/materials/professor-materials-client.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit the role dashboards**

```powershell
git add -- apps/frontend/app/components/dashboard/role-dashboard.tsx apps/frontend/app/components/dashboard/role-dashboard.test.tsx apps/frontend/app/student/page.tsx apps/frontend/app/professor/page.tsx apps/frontend/app/admin/page.tsx apps/frontend/app/components/auth/role-page.tsx apps/frontend/app/globals.css
git commit -m "Add role-specific Canvas dashboards"
```

### Task 5: Integrate Existing Feature Pages and Verify the Whole Story

**Files:**
- Modify: `apps/frontend/app/globals.css`
- Verify: all files under `apps/frontend/app/admin`, `apps/frontend/app/professor`, `apps/frontend/app/student`, and `apps/frontend/app/course-agent`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a verified login-to-role-dashboard-to-feature flow at desktop and mobile sizes.

- [ ] **Step 1: Run the complete frontend test suite**

Run:

```powershell
npm.cmd test --workspace @skku-course-agent/frontend
```

Expected: all tests PASS. If a test fails, fix the smallest regression in the file named by the failure and rerun that test before rerunning the suite.

- [ ] **Step 2: Run static verification**

Run:

```powershell
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build:frontend
```

Expected: each command exits 0 with no TypeScript, ESLint, or Next.js build error.

- [ ] **Step 3: Start the API and web app with the repository commands**

In separate terminals:

```powershell
make dev-api
```

```powershell
npm.cmd run dev:frontend
```

Expected: FastAPI listens on port 8000 and Next.js listens on port 3000.

- [ ] **Step 4: Verify the login screen in Chrome**

Open `http://localhost:3000/login` and confirm:

- local horizontal i-Campus logo loads;
- ID and Password fields form one flat block;
- green `LOGIN` button matches the approved screen;
- no console error is present.

- [ ] **Step 5: Verify student, professor, and administrator flows**

Using the repository seed accounts, verify one role at a time:

- student: login redirects to `/student`; global and student menus show icons; `/student/courses` and `/student/chat` open;
- professor: login redirects to `/professor`; global and professor menus show icons; `/professor/courses` and `/professor/materials` open;
- administrator: login redirects to `/admin`; global and administrator menus show icons; `/admin/courses`, `/admin/users`, and `/admin/materials` open.

Confirm active links are reflected in both icon/color state and `aria-current`.

- [ ] **Step 6: Verify responsive behavior**

At 1440x900, 820x1180, and 390x844:

- no global menu, context menu, table, or card overlaps the main content;
- desktop retains the 84px and 220px columns;
- tablet and mobile navigation remains keyboard reachable;
- administrator tables scroll horizontally instead of clipping.

- [ ] **Step 7: Inspect the final diff without touching unrelated changes**

Run:

```powershell
git status --short
git diff --check
git diff -- apps/frontend
```

Expected: only intended frontend files plus the pre-existing
`apps/frontend/next-env.d.ts` working-tree change are visible; the latter is not
staged or modified by this work.

- [ ] **Step 8: Commit final responsive fixes**

If Step 4-6 required CSS changes:

```powershell
git add -- apps/frontend/app/globals.css
git commit -m "Polish i-Campus responsive layout"
```

If no changes were required, do not create an empty commit.
