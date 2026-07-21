import { CourseFormClient } from "../../../courses/course-form-client";

export default async function AdminCourseSettingsPage({
  params
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return <CourseFormClient courseId={courseId} mode="edit" />;
}
