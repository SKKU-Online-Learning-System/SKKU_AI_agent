import { RolePage } from "../../components/auth/role-page";

export default function ProfessorCoursesPage() {
  return (
    <RolePage
      description="본인이 담당 교수자로 등록된 과목만 표시됩니다."
      items={["과목 목록", "수업 자료", "질문 로그"]}
      title="담당 과목"
    />
  );
}
