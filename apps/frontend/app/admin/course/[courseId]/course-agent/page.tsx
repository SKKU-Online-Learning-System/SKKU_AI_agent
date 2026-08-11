"use client";

import { useParams } from "next/navigation";
import { CourseAgentSettingsClient } from "../../../../components/course-agent/course-agent-settings-client";

export default function AdminCourseAgentPage() {
  const params = useParams<{ courseId: string }>();
  return <CourseAgentSettingsClient courseId={params.courseId} />;
}
