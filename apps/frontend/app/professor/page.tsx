import { RolePage } from "../components/auth/role-page";

export default function ProfessorDashboardPage() {
  return (
    <RolePage
      description="담당 과목 자료와 학생 질문 흐름을 확인하는 교수자 화면입니다."
      items={["담당 과목", "최근 업로드", "질문 로그"]}
      title="교수자 대시보드"
    />
  );
}
