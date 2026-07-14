import { RolePage } from "../../components/auth/role-page";

export default function AdminCoursesPage() {
  return (
    <RolePage
      description="과목 생성, 담당 교수자 지정, 활성화 상태 관리를 준비 중입니다."
      items={["과목 목록", "과목 생성", "활성화 관리"]}
      title="과목 관리"
    />
  );
}
