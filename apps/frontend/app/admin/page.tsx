import { RolePage } from "../components/auth/role-page";

export default function AdminDashboardPage() {
  return (
    <RolePage
      description="전체 사용자, 과목, 자료 현황을 관리하는 운영 화면입니다."
      items={["전체 과목", "사용자 권한", "자료 처리 상태", "사용 로그"]}
      title="관리자 대시보드"
    />
  );
}
