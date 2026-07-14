import { RolePage } from "../../components/auth/role-page";

export default function StudentChatPage() {
  return (
    <RolePage
      description="선택한 과목의 업로드 자료를 우선 사용하는 챗봇 화면입니다."
      items={["과목 선택", "질문 입력", "출처 확인"]}
      title="챗봇"
    />
  );
}
