"""Prompt templates for the course agent.

Every template lives here so answer policy changes (hint mode, exam mode, and so
on) stay in one place instead of spreading through the chat route.
"""

from __future__ import annotations

from typing import Optional, Sequence

from app.core.config import Settings
from app.services.llm_service import ChatMessage
from app.services.vector_store_service import SearchResult

AnswerPolicy = str

BASE_SYSTEM_PROMPT = """너는 성균관대학교 수업을 돕는 교육용 코스 에이전트다.

기본 원칙:
- 제공된 강의자료 컨텍스트를 우선 근거로 답변한다.
- 강의자료에 없는 내용은 확정적으로 말하지 않는다.
- 근거가 부족하면 "강의자료에서 직접 확인된 내용은 부족합니다"라고 밝힌다.
- 과제나 시험의 정답을 그대로 요구받으면 정답 대신 개념 설명, 접근 방법, 단계별 힌트를 제공한다.
- 학생이 스스로 이해할 수 있도록 친절하고 명확하게 설명한다.
- 기본적으로 한국어로 답변하고, 영어 질문에는 영어로 답해도 된다.
- 출처 번호나 문서 목록을 임의로 지어내지 않는다. 출처는 서버가 따로 표시한다."""

POLICY_INSTRUCTIONS = {
    "grounded": (
        "제공된 강의자료 컨텍스트를 근거로 답변해라. "
        "컨텍스트에 없는 내용을 덧붙일 때는 일반적인 설명임을 밝혀라."
    ),
    "hint": (
        "정답 전체나 제출 가능한 완성물을 제공하지 마라. "
        "핵심 개념, 접근 순서, 확인해야 할 포인트를 단계별 힌트로 제시해라. "
        "학생이 직접 완성할 수 있도록 안내하는 어조를 유지해라."
    ),
    "general": (
        "이 과목의 강의자료에서 근거를 찾지 못했다. "
        "일반적인 개념 설명을 제공하되, 강의자료에서 확인된 내용이라고 말하지 마라. "
        "학사 정책, 과제 조건, 시험 범위처럼 확인이 필요한 내용은 교수자 안내를 확인하라고 말해라."
    ),
}


class PromptBuilderService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_rag_prompt(
        self,
        *,
        course_name: str,
        question: str,
        retrieved_chunks: Sequence[SearchResult],
        answer_policy: AnswerPolicy = "grounded",
        safety_note: Optional[str] = None,
    ) -> list[ChatMessage]:
        system_parts = [BASE_SYSTEM_PROMPT, f"현재 과목: {course_name}"]
        instruction = POLICY_INSTRUCTIONS.get(answer_policy, POLICY_INSTRUCTIONS["grounded"])
        system_parts.append(f"[답변 지침]\n{instruction}")
        if safety_note:
            system_parts.append(f"[안전 지침]\n{safety_note}")

        context = self.format_context(retrieved_chunks)
        user_parts = [f"[질문]\n{question.strip()}"]
        user_parts.append(
            f"[강의자료 컨텍스트]\n{context}" if context else "[강의자료 컨텍스트]\n(없음)"
        )

        return [
            ChatMessage(role="system", content="\n\n".join(system_parts)),
            ChatMessage(role="user", content="\n\n".join(user_parts)),
        ]

    def format_context(self, retrieved_chunks: Sequence[SearchResult]) -> str:
        """Join the retrieved chunks, stopping before the context budget is exceeded."""

        blocks: list[str] = []
        remaining = self.settings.max_context_chars

        for result in retrieved_chunks:
            page = result.page_number if result.page_number is not None else "페이지 정보 없음"
            header = f"[출처 {len(blocks) + 1}] {result.document_name} (p.{page})"
            block = f"{header}\n{result.chunk_text.strip()}"
            if len(block) > remaining:
                break

            blocks.append(block)
            remaining -= len(block)

        return "\n\n---\n\n".join(blocks)
