"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { StudyPageClient } from "../../../components/study/study-page-client";

export default function StudentCoursePage() {
  const params = useParams<{ courseId: string }>();
  return (
    <Suspense fallback={null}>
      <StudyPageClient courseId={params.courseId} />
    </Suspense>
  );
}
