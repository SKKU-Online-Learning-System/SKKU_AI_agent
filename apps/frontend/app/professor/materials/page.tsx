import { RolePage } from "../../components/auth/role-page";

export default function ProfessorMaterialsPage() {
  return (
    <RolePage
      description="담당 과목에 강의자료를 업로드하고 처리 상태를 확인하는 화면입니다."
      items={["자료 업로드", "처리 대기", "처리 완료"]}
      title="자료 업로드"
    />
  );
}
