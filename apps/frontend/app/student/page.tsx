import { RolePage } from "../components/auth/role-page";

export default function StudentDashboardPage() {
  return (
    <RolePage
      description="접근 가능한 활성 과목과 학습 질문 흐름을 확인하는 학생 화면입니다."
      items={["내 과목", "최근 질문", "출처 기반 답변"]}
      title="학생 대시보드"
    />
  );
}
