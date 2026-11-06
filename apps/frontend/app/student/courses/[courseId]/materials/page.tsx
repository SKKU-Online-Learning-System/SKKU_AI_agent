import { redirect } from "next/navigation";

/** 강의콘텐츠 is the study page itself now; the old tab lands on it with the curriculum open. */
export default async function StudentCourseMaterialsPage({
  params
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  redirect(`/student/courses/${courseId}?panel=curriculum`);
}
