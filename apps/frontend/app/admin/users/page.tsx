import { RolePage } from "../../components/auth/role-page";

export default function AdminUsersPage() {
  return (
    <RolePage
      description="학생, 교수자, 관리자 계정과 역할 권한을 관리하는 화면입니다."
      items={["사용자 목록", "역할 변경", "접근 권한"]}
      title="사용자 관리"
    />
  );
}
