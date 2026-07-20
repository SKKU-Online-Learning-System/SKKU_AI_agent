import type { Course, CourseMaterial } from "@skku-course-agent/shared";
import type { DemoMessage, PersonalityId } from "./state";
import type { IconName } from "./ui-icon";

const now = new Date("2026-07-09T00:00:00.000Z").toISOString();

export const activeCourse: Course = {
  id: "course-ai-101",
  code: "SWE2026_41",
  title: "문제해결 SWE2026_41(조재민)",
  term: "2026-1",
  instructorId: "user-prof-kim",
  instructorName: "김교수",
  agentStatus: "active",
  createdAt: now,
  updatedAt: now
};

export const materials: CourseMaterial[] = [
  {
    id: "material-week-01",
    courseId: activeCourse.id,
    uploadedBy: "user-prof-kim",
    title: "1주차 강의자료",
    fileName: "week01-introduction.pdf",
    fileType: "application/pdf",
    storageUri: "local://uploads/course-ai-101/week01-introduction.pdf",
    status: "ready",
    checksum: null,
    createdAt: now,
    updatedAt: now
  },
  {
    id: "material-week-02",
    courseId: activeCourse.id,
    uploadedBy: "user-prof-kim",
    title: "2주차 RAG 개요",
    fileName: "week02-rag.pdf",
    fileType: "application/pdf",
    storageUri: "local://uploads/course-ai-101/week02-rag.pdf",
    status: "processing",
    checksum: null,
    createdAt: now,
    updatedAt: now
  },
  {
    id: "material-week-03",
    courseId: activeCourse.id,
    uploadedBy: "user-prof-kim",
    title: "3주차 프롬프트 설계",
    fileName: "week03-prompt-design.pdf",
    fileType: "application/pdf",
    storageUri: "local://uploads/course-ai-101/week03-prompt-design.pdf",
    status: "failed",
    checksum: null,
    createdAt: now,
    updatedAt: now
  }
];

export const studentInitialMessages: DemoMessage[] = [
  {
    id: "student-message-001",
    role: "user",
    message: "RAG가 일반 LLM 질의응답과 다른 점은 무엇인가요?",
    citations: []
  },
  {
    id: "student-message-002",
    role: "assistant",
    message:
      "RAG는 질문과 관련된 강의자료 조각을 먼저 검색한 뒤, 그 근거를 함께 사용해 답변을 생성합니다. 그래서 업로드된 수업 자료를 우선 반영하고, 답변 하단에서 참고한 자료를 확인할 수 있습니다.",
    citations: [{ title: "2주차 RAG 개요", page: 7 }]
  }
];

export const professorInitialMessages: DemoMessage[] = [
  {
    id: "professor-message-001",
    role: "assistant",
    message: "교수님, 선택한 강의콘텐츠를 기준으로 수업 자료를 점검하거나 질문에 답변해 드립니다.",
    citations: []
  }
];

export const personalityOptions: Array<{
  id: PersonalityId;
  label: string;
  description: string;
}> = [
  { id: "default", label: "기본", description: "명확하고 중립적" },
  { id: "professional", label: "전문적", description: "정교하고 격식 있는 설명" },
  { id: "friendly", label: "친근함", description: "따뜻하고 대화하듯 설명" },
  { id: "candid", label: "솔직함", description: "핵심과 개선점을 직접 제시" },
  { id: "quirky", label: "개성 있음", description: "창의적인 비유와 가벼운 유머" },
  { id: "efficient", label: "효율적", description: "짧고 빠르게 핵심만 설명" },
  { id: "cynical", label: "냉소적", description: "건조한 유머와 실용적인 답변" }
];

export const railItems: Array<{ label: string; icon: IconName; active?: boolean }> = [
  { label: "계정", icon: "account" },
  { label: "대시보드", icon: "dashboard" },
  { label: "과목", icon: "course", active: true },
  { label: "그룹", icon: "group" },
  { label: "캘린더", icon: "calendar" },
  { label: "메시지함", icon: "message" },
  { label: "전체게시물", icon: "posts" },
  { label: "마이페이지", icon: "mypage" },
  { label: "이용안내", icon: "info" },
  { label: "시간표", icon: "timetable" }
];

export const courseNavItems: Array<{ label: string; icon: IconName; active?: boolean }> = [
  { label: "홈", icon: "home" },
  { label: "강의콘텐츠", icon: "content" },
  { label: "출결현황", icon: "attendance" },
  { label: "성적", icon: "grade" },
  { label: "AI 코스 에이전트", icon: "agent", active: true }
];
