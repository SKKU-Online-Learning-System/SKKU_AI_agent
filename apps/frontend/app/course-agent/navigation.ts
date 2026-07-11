import type { AgentRole, ScreenId } from "./state";
import type { IconName } from "./ui-icon";

export type NavigationItem = { id: ScreenId; label: string; icon: IconName };

export const roleNavigation: Record<AgentRole, NavigationItem[]> = {
  student: [
    { id: "student-login", label: "로그인", icon: "account" },
    { id: "student-courses", label: "과목 목록", icon: "course" },
    { id: "student-chat", label: "AI 코스 에이전트", icon: "agent" },
    { id: "student-history", label: "최근 대화", icon: "message" }
  ],
  professor: [
    { id: "professor-dashboard", label: "교수자 대시보드", icon: "dashboard" },
    { id: "professor-materials", label: "강의자료", icon: "material" },
    { id: "professor-settings", label: "에이전트 설정", icon: "agent" },
    { id: "professor-logs", label: "질문 로그", icon: "posts" }
  ],
  admin: [
    { id: "admin-dashboard", label: "관리자 대시보드", icon: "dashboard" },
    { id: "admin-courses", label: "과목 관리", icon: "course" },
    { id: "admin-users", label: "사용자 및 권한", icon: "group" },
    { id: "admin-materials", label: "전체 자료", icon: "material" },
    { id: "admin-logs", label: "전체 로그", icon: "posts" }
  ]
};

export function getDefaultScreen(role: AgentRole): ScreenId {
  if (role === "student") return "student-chat";
  if (role === "professor") return "professor-dashboard";
  return "admin-dashboard";
}
