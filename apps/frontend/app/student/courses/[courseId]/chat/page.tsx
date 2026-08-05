"use client";

import { useParams, useSearchParams } from "next/navigation";
import { ChatClient } from "../../../../components/chat/chat-client";

export default function StudentCourseChatPage() {
  const params = useParams<{ courseId: string }>();
  const searchParams = useSearchParams();

  return (
    <ChatClient
      courseId={params.courseId}
      initialSessionId={searchParams.get("sessionId")}
    />
  );
}
