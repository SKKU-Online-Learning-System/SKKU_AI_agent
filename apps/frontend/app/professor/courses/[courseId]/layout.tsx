import { CourseWorkspaceClient } from "../../../components/courses/course-workspace-client";

export default async function ProfessorCourseLayout({
  children,
  params
}: {
  children: React.ReactNode;
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return (
    <CourseWorkspaceClient courseId={courseId} role="professor">
      {children}
    </CourseWorkspaceClient>
  );
}
