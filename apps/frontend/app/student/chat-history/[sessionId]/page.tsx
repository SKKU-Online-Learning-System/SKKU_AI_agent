"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, getChatSession } from "../../../lib/api";
import { ChatClient } from "../../../components/chat/chat-client";

export default function StudentChatSessionPage() {
  const params = useParams<{ sessionId: string }>();
  const [courseId, setCourseId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;

    async function loadSession() {
      try {
        const detail = await getChatSession(params.sessionId);
        if (!isCancelled) setCourseId(detail.session.courseId);
      } catch (error) {
        if (!isCancelled) {
          setErrorMessage(
            error instanceof ApiError ? error.message : "대화를 불러오지 못했습니다."
          );
        }
      }
    }

    void loadSession();

    return () => {
      isCancelled = true;
    };
  }, [params.sessionId]);

  if (errorMessage) {
    return (
      <p className="admin-alert" role="alert">
        {errorMessage}
      </p>
    );
  }
  if (!courseId) {
    return <p className="empty-state">대화를 불러오고 있습니다.</p>;
  }

  return <ChatClient courseId={courseId} initialSessionId={params.sessionId} />;
}
