import { CourseMaterialsClient } from "../../../../components/courses/course-materials-client";

export default async function AdminCourseMaterialsPage({
  params
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return <CourseMaterialsClient courseId={courseId} />;
}
