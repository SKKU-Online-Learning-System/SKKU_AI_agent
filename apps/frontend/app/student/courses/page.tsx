import { RolePage } from "../../components/auth/role-page";

export default function StudentCoursesPage() {
  return (
    <RolePage
      description="CourseAccess에 등록된 활성 과목만 표시됩니다."
      items={["수강 과목", "강의자료", "학습 기록"]}
      title="내 과목"
    />
  );
}
