import { RoleDashboard } from "../components/dashboard/role-dashboard";

export default function AdminDashboardPage() {
  return (
    <RoleDashboard
      actions={[
        {
          href: "/admin/courses",
          label: "과목 관리",
          description: "과목을 등록하고 활성 상태를 관리합니다.",
          icon: "course"
        },
        {
          href: "/admin/users",
          label: "사용자 관리",
          description: "사용자 역할과 접근 권한을 확인합니다.",
          icon: "group"
        },
        {
          href: "/admin/materials",
          label: "자료 관리",
          description: "전체 자료와 처리 상태를 확인합니다.",
          icon: "material"
        }
      ]}
      description="관리자 운영 화면입니다."
      title="대시보드"
    />
  );
}
