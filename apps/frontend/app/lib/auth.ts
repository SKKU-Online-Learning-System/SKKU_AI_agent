import type { UserRole } from "@skku-course-agent/shared";
import type { IconName } from "../components/ui/ui-icon";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  role: UserRole;
};

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export type RoleMenuItem = {
  href: string;
  label: string;
  icon: IconName;
};

/** One entry of the i-Campus global rail; `href` is null when unimplemented. */
export type GlobalNavItem = {
  href: string | null;
  label: string;
  icon: IconName;
};

export const roleLabels: Record<UserRole, string> = {
  admin: "관리자",
  professor: "교수자",
  student: "학생"
};

export const roleHomePaths: Record<UserRole, string> = {
  admin: "/admin",
  professor: "/professor",
  student: "/student"
};

const roleMenuItems: Record<UserRole, RoleMenuItem[]> = {
  admin: [
    { href: "/admin", label: "대시보드", icon: "dashboard" },
    { href: "/admin/courses", label: "과목", icon: "course" },
    { href: "/admin/users", label: "사용자", icon: "group" },
    { href: "/admin/materials", label: "자료", icon: "material" },
    { href: "/admin/logs", label: "질문 로그", icon: "agent" }
  ],
  professor: [
    { href: "/professor", label: "대시보드", icon: "dashboard" },
    { href: "/professor/courses", label: "해당 과목", icon: "course" },
    { href: "/professor/materials", label: "강의자료", icon: "material" },
    { href: "/professor/logs", label: "질문 로그", icon: "agent" },
    { href: "/professor/rag-debug", label: "RAG 디버그", icon: "source" }
  ],
  // Questions are asked inside a course, through COURSE AGENT.
  student: [
    { href: "/student", label: "대시보드", icon: "dashboard" },
    { href: "/student/courses", label: "내 과목", icon: "course" },
    { href: "/student/chat-history", label: "대화 이력", icon: "material" }
  ]
};

const coursesPaths: Record<UserRole, string> = {
  admin: "/admin/courses",
  professor: "/professor/courses",
  student: "/student/courses"
};

/**
 * The nine i-Campus rail entries, in the order canvas.skku.edu renders them.
 * Entries this MVP does not implement stay in place, greyed out, so the shell
 * still reads as i-Campus instead of a shortened imitation.
 */
export function getGlobalNavItems(role: UserRole): GlobalNavItem[] {
  return [
    { href: null, label: "계정", icon: "account" },
    { href: roleHomePaths[role], label: "대시보드", icon: "dashboard" },
    { href: coursesPaths[role], label: "과목", icon: "course" },
    { href: null, label: "그룹", icon: "group" },
    { href: null, label: "캘린더", icon: "calendar" },
    { href: null, label: "메시지함", icon: "message" },
    { href: null, label: "전체게시물", icon: "posts" },
    { href: null, label: "마이페이지", icon: "mypage" },
    { href: null, label: "이용안내", icon: "info" }
  ];
}

export function getRoleHomePath(role: UserRole): string {
  return roleHomePaths[role];
}

export function getRoleMenuItems(role: UserRole): RoleMenuItem[] {
  return roleMenuItems[role];
}

export function canAccessRole(userRole: UserRole, allowedRoles: UserRole[]): boolean {
  return allowedRoles.includes(userRole);
}
