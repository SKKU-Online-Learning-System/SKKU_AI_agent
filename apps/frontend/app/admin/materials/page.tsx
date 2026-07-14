import { RolePage } from "../../components/auth/role-page";

export default function AdminMaterialsPage() {
  return (
    <RolePage
      description="전체 과목의 업로드 자료와 처리 상태를 확인하는 화면입니다."
      items={["자료 목록", "처리 상태", "오류 확인"]}
      title="자료 관리"
    />
  );
}
