"use client";

import { useParams, useSearchParams } from "next/navigation";
import { CourseAgentClient } from "../../../../components/course-agent/course-agent-client";

export default function StudentCourseAgentPage() {
  const params = useParams<{ courseId: string }>();
  const searchParams = useSearchParams();

  return (
    <CourseAgentClient
      courseId={params.courseId}
      initialSessionId={searchParams.get("sessionId")}
    />
  );
}
