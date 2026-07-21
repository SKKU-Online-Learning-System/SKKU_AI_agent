import { RoleDashboard } from "../components/dashboard/role-dashboard";

export default function ProfessorDashboardPage() {
  return (
    <RoleDashboard
      actions={[
        {
          href: "/professor/courses",
          label: "담당 과목",
          description: "담당 과목과 에이전트 상태를 확인합니다.",
          icon: "course"
        },
        {
          href: "/professor/materials",
          label: "강의자료",
          description: "자료를 업로드하고 처리 상태를 확인합니다.",
          icon: "material"
        }
      ]}
      description="교수자 운영 화면입니다."
      title="대시보드"
    />
  );
}
