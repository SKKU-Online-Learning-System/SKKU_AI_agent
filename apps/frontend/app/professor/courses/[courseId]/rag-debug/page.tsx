import { RagDebugClient } from "../../../../components/courses/rag-debug-client";

export default async function CourseRagDebugPage({
  params
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return <RagDebugClient courseId={courseId} />;
}
