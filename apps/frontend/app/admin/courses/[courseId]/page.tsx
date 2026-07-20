"use client";

import { useParams } from "next/navigation";
import { CourseFormClient } from "../course-form-client";

export default function AdminCourseDetailPage() {
  const params = useParams<{ courseId: string }>();

  return <CourseFormClient courseId={params.courseId} mode="edit" />;
}
