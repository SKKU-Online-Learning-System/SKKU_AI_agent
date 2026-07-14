import type { UserRole } from "@skku-course-agent/shared";

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
    { href: "/admin", label: "관리자 대시보드" },
    { href: "/admin/courses", label: "과목 관리" },
    { href: "/admin/users", label: "사용자 관리" },
    { href: "/admin/materials", label: "자료 관리" }
  ],
  professor: [
    { href: "/professor", label: "교수자 대시보드" },
    { href: "/professor/courses", label: "담당 과목" },
    { href: "/professor/materials", label: "자료 업로드" }
  ],
  student: [
    { href: "/student", label: "학생 대시보드" },
    { href: "/student/courses", label: "내 과목" },
    { href: "/student/chat", label: "챗봇" }
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
