import { getDefaultScreen } from "./navigation";

export type AgentRole = "student" | "professor" | "admin";
export type ScreenId =
  | "student-login"
  | "student-courses"
  | "student-chat"
  | "student-history"
  | "professor-dashboard"
  | "professor-materials"
  | "professor-settings"
  | "professor-logs"
  | "admin-dashboard"
  | "admin-courses"
  | "admin-users"
  | "admin-materials"
  | "admin-logs";
export type PersonalityId =
  | "default"
  | "professional"
  | "friendly"
  | "candid"
  | "quirky"
  | "efficient"
  | "cynical";

export type AttachmentItem = {
  id: string;
  name: string;
  size: number;
  type: string;
  previewUrl?: string;
};

export type DemoMessage = {
  id: string;
  role: "user" | "assistant";
  message: string;
  citations: Array<{ title: string; page?: number }>;
  insufficient?: boolean;
};

export type CourseAgentState = {
  activeRole: AgentRole;
  activeScreen: ScreenId;
  student: {
    personality: PersonalityId;
    attachments: AttachmentItem[];
    messages: DemoMessage[];
  };
  professor: {
    selectedMaterialIds: string[];
    attachments: AttachmentItem[];
    messages: DemoMessage[];
  };
  admin: {
    attachments: AttachmentItem[];
    messages: DemoMessage[];
  };
};

export type CourseAgentAction =
  | { type: "set-role"; role: AgentRole }
  | { type: "set-screen"; screen: ScreenId }
  | { type: "set-personality"; personality: PersonalityId }
  | { type: "toggle-material"; materialId: string; selectable: boolean }
  | { type: "set-materials"; materialIds: string[] }
  | { type: "add-attachments"; role: AgentRole; attachments: AttachmentItem[] }
  | { type: "remove-attachment"; role: AgentRole; attachmentId: string }
  | { type: "add-message"; role: AgentRole; message: DemoMessage };

export function createInitialState(): CourseAgentState {
  return {
    activeRole: "student",
    activeScreen: "student-chat",
    student: { personality: "default", attachments: [], messages: [] },
    professor: {
      selectedMaterialIds: ["material-week-01"],
      attachments: [],
      messages: []
    },
    admin: { attachments: [], messages: [] }
  };
}

export function validateAttachment(file: File, role: AgentRole): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const allowed =
    role === "professor"
      ? ["pdf", "pptx", "docx", "txt"]
      : ["pdf", "docx", "txt", "png", "jpg", "jpeg"];
  const limitMb = role === "professor" ? 20 : 10;
  if (!allowed.includes(extension)) {
    return role === "professor"
      ? "PDF, PPTX, DOCX, TXT 파일만 첨부할 수 있습니다."
      : "PDF, DOCX, TXT, PNG, JPG, JPEG 파일만 첨부할 수 있습니다.";
  }
  if (file.size > limitMb * 1024 * 1024) {
    return `${role === "professor" ? "교수 참고 문서" : "학생 첨부 파일"}는 파일당 ${limitMb}MB 이하만 첨부할 수 있습니다.`;
  }
  return null;
}

export function courseAgentReducer(
  state: CourseAgentState,
  action: CourseAgentAction
): CourseAgentState {
  if (action.type === "set-role") {
    return { ...state, activeRole: action.role, activeScreen: getDefaultScreen(action.role) };
  }
  if (action.type === "set-screen") return { ...state, activeScreen: action.screen };
  if (action.type === "set-personality") {
    return { ...state, student: { ...state.student, personality: action.personality } };
  }
  if (action.type === "toggle-material") {
    if (!action.selectable) return state;
    const selected = state.professor.selectedMaterialIds.includes(action.materialId);
    return {
      ...state,
      professor: {
        ...state.professor,
        selectedMaterialIds: selected
          ? state.professor.selectedMaterialIds.filter((id) => id !== action.materialId)
          : [...state.professor.selectedMaterialIds, action.materialId]
      }
    };
  }
  if (action.type === "set-materials") {
    return { ...state, professor: { ...state.professor, selectedMaterialIds: action.materialIds } };
  }
  if (action.type === "add-attachments") {
    if (action.role === "student") {
      return {
        ...state,
        student: {
          ...state.student,
          attachments: [...state.student.attachments, ...action.attachments]
        }
      };
    }
    return {
      ...state,
      professor: {
        ...state.professor,
        attachments: [...state.professor.attachments, ...action.attachments]
      }
    };
  }
  if (action.type === "remove-attachment") {
    if (action.role === "student") {
      return {
        ...state,
        student: {
          ...state.student,
          attachments: state.student.attachments.filter(
            (attachment) => attachment.id !== action.attachmentId
          )
        }
      };
    }
    return {
      ...state,
      professor: {
        ...state.professor,
        attachments: state.professor.attachments.filter(
          (attachment) => attachment.id !== action.attachmentId
        )
      }
    };
  }
  if (action.role === "student") {
    return {
      ...state,
      student: {
        ...state.student,
        messages: [...state.student.messages, action.message]
      }
    };
  }
  if (action.role === "professor") return {
    ...state,
    professor: {
      ...state.professor,
      messages: [...state.professor.messages, action.message]
    }
  };
  return {
    ...state,
    admin: { ...state.admin, messages: [...state.admin.messages, action.message] }
  };
}
