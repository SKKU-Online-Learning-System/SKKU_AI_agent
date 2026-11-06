import { redirect } from "next/navigation";

/**
 * COURSE AGENT lives in the study page's drawer. 대화 이력 still links here with
 * `?sessionId=`, which the study page passes on so the conversation is rehydrated.
 */
export default async function StudentCourseAgentPage({
  params,
  searchParams
}: {
  params: Promise<{ courseId: string }>;
  searchParams: Promise<{ sessionId?: string }>;
}) {
  const { courseId } = await params;
  const { sessionId } = await searchParams;
  const query = new URLSearchParams({ panel: "agent" });
  if (sessionId) query.set("sessionId", sessionId);
  redirect(`/student/courses/${courseId}?${query.toString()}`);
}
