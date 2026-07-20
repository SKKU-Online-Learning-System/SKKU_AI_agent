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
    { href: "/admin/materials", label: "자료", icon: "material" }
  ],
  professor: [
    { href: "/professor", label: "대시보드", icon: "dashboard" },
    { href: "/professor/courses", label: "해당 과목", icon: "course" },
    { href: "/professor/materials", label: "강의자료", icon: "material" }
  ],
  student: [
    { href: "/student", label: "대시보드", icon: "dashboard" },
    { href: "/student/courses", label: "내 과목", icon: "course" },
    { href: "/student/chat", label: "AI 질문", icon: "agent" }
  ]
};

export function getRoleHomePath(role: UserRole): string {
  return roleHomePaths[role];
}

export function getRoleMenuItems(role: UserRole): RoleMenuItem[] {
  return roleMenuItems[role];
}

export function canAccessRole(userRole: UserRole, allowedRoles: UserRole[]): boolean {
  return allowedRoles.includes(userRole);
}
