import { CourseWorkspaceClient } from "../../../components/courses/course-workspace-client";

export default async function AdminCourseLayout({
  children,
  params
}: {
  children: React.ReactNode;
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return (
    <CourseWorkspaceClient courseId={courseId} role="admin">
      {children}
    </CourseWorkspaceClient>
  );
}
