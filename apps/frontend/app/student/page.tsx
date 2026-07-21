import { RoleDashboard } from "../components/dashboard/role-dashboard";

export default function StudentDashboardPage() {
  return (
    <RoleDashboard
      actions={[
        {
          href: "/student/courses",
          label: "내 과목",
          description: "수강 가능한 활성 과목을 확인합니다.",
          icon: "course"
        },
        {
          href: "/student/chat",
          label: "AI 질문",
          description: "강의자료를 근거로 질문하고 출처를 확인합니다.",
          icon: "agent"
        }
      ]}
      description="학생 학습 화면입니다."
      title="대시보드"
    />
  );
}
