import { CourseHomeClient } from "../../../components/courses/course-home-client";

export default async function ProfessorCourseHomePage({
  params
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return <CourseHomeClient courseId={courseId} role="professor" />;
}
