"""Question to answer orchestration for the course chatbot.

One call runs safety classification, course-scoped retrieval, prompt building,
answer generation and log persistence. Sources are always built from the search
results on the server, never from anything the model writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import ChatAnswerSourceType, ChatLog, ChatSession, Course, User
from app.services.embedding_service import EmbeddingError
from app.services.llm_service import LLMError, LLMService
from app.services.prompt_service import PromptBuilderService
from app.services.rag_service import RagService, RetrievalSummary
from app.services.safety_service import (
    HINT_SAFETY_NOTE,
    REDIRECT_HINT,
    SafetyGuardService,
    SafetyResult,
)
from app.services.vector_store_service import SearchResult

logger = logging.getLogger(__name__)

INSUFFICIENT_CONTEXT_NOTICE = (
    "강의자료에서 직접 확인된 내용은 부족합니다. 아래 내용은 일반적인 개념 설명입니다."
)
NO_MATERIAL_NOTICE = (
    "아직 이 과목의 강의자료가 충분히 처리되지 않아 강의자료 기반 답변을 제공하기 어렵습니다. "
    "아래 내용은 일반적인 개념 설명입니다."
)
TITLE_MAX_LENGTH = 40


class ChatValidationError(Exception):
    code = "VALIDATION_ERROR"


class ChatSessionNotFoundError(Exception):
    code = "CHAT_SESSION_NOT_FOUND"


class ChatSessionAccessError(Exception):
    code = "CHAT_SESSION_ACCESS_DENIED"


class AnswerGenerationError(Exception):
    def __init__(self, message: str, code: str = "LLM_GENERATION_FAILED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AnswerSource:
    material_id: str
    document_name: str
    page_number: Optional[int]
    chunk_index: int
    score: float

    def as_dict(self) -> dict:
        return {
            "material_id": self.material_id,
            "document_name": self.document_name,
            "page_number": self.page_number,
            "chunk_index": self.chunk_index,
            "score": self.score,
        }


@dataclass(frozen=True)
class ChatAnswer:
    session_id: str
    log_id: str
    answer: str
    sources: list[AnswerSource]
    is_grounded: bool
    answer_source_type: str
    model_name: Optional[str]
    response_time_ms: int
    summary: RetrievalSummary
    safety: SafetyResult


class ChatService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        rag_service: Optional[RagService] = None,
        llm_service: Optional[LLMService] = None,
        prompt_builder: Optional[PromptBuilderService] = None,
        safety_guard: Optional[SafetyGuardService] = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.rag_service = rag_service or RagService(session, settings)
        self.llm_service = llm_service or LLMService(settings)
        self.prompt_builder = prompt_builder or PromptBuilderService(settings)
        self.safety_guard = safety_guard or SafetyGuardService()

    def answer_question(
        self,
        *,
        user: User,
        course: Course,
        question: str,
        chat_session_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> ChatAnswer:
        started = perf_counter()
        cleaned = self._validate_question(question)
        chat_session = self._resolve_session(user, course, chat_session_id)
        safety = self.safety_guard.check_question(cleaned)

        if safety.blocked:
            outcome = self.rag_service.retrieve(course.id, cleaned, 1)
            answer = safety.safe_answer or "요청하신 내용은 도와드릴 수 없습니다."
            return self._persist(
                chat_session=chat_session,
                user=user,
                course=course,
                question=cleaned,
                answer=answer,
                sources=[],
                is_grounded=False,
                answer_source_type=ChatAnswerSourceType.safety_response,
                model_name=None,
                summary=outcome.summary,
                safety=safety,
                started=started,
            )

        try:
            outcome = self.rag_service.retrieve(course.id, cleaned, top_k)
        except EmbeddingError as error:
            raise AnswerGenerationError(str(error), "RAG_SEARCH_FAILED") from error

        results = outcome.results
        is_grounded = bool(results)
        answer_source_type = self._resolve_source_type(is_grounded, outcome.summary)
        answer_policy = REDIRECT_HINT if safety.redirect_type == REDIRECT_HINT else None

        messages = self.prompt_builder.build_rag_prompt(
            course_name=course.name,
            question=cleaned,
            retrieved_chunks=results,
            answer_policy=answer_policy or ("grounded" if is_grounded else "general"),
            safety_note=HINT_SAFETY_NOTE if answer_policy == REDIRECT_HINT else None,
        )

        try:
            generated = self.llm_service.generate_answer(messages)
        except LLMError as error:
            raise AnswerGenerationError(str(error)) from error

        answer = self._apply_notice(generated.answer, answer_source_type)
        return self._persist(
            chat_session=chat_session,
            user=user,
            course=course,
            question=cleaned,
            answer=answer,
            sources=build_sources(results) if is_grounded else [],
            is_grounded=is_grounded,
            answer_source_type=answer_source_type,
            model_name=generated.model_name,
            summary=outcome.summary,
            safety=safety,
            started=started,
        )

    def create_session(self, user: User, course: Course, title: Optional[str] = None) -> ChatSession:
        chat_session = ChatSession(user_id=user.id, course_id=course.id, title=title)
        self.session.add(chat_session)
        self.session.commit()
        self.session.refresh(chat_session)
        return chat_session

    def load_owned_session(self, user: User, session_id: str) -> ChatSession:
        chat_session = self.session.get(ChatSession, session_id)
        if chat_session is None:
            raise ChatSessionNotFoundError("대화를 찾을 수 없습니다.")
        if chat_session.user_id != user.id:
            raise ChatSessionAccessError("다른 사용자의 대화는 조회할 수 없습니다.")

        return chat_session

    def _validate_question(self, question: str) -> str:
        cleaned = (question or "").strip()
        if not cleaned:
            raise ChatValidationError("질문을 입력해 주세요.")
        if len(cleaned) > self.settings.max_question_length:
            raise ChatValidationError(
                f"질문은 {self.settings.max_question_length}자를 넘을 수 없습니다."
            )

        return cleaned

    def _resolve_session(
        self,
        user: User,
        course: Course,
        chat_session_id: Optional[str],
    ) -> ChatSession:
        if chat_session_id is None:
            return self.create_session(user, course)

        chat_session = self.load_owned_session(user, chat_session_id)
        if chat_session.course_id != course.id:
            raise ChatSessionAccessError("대화와 과목이 일치하지 않습니다.")

        return chat_session

    def _resolve_source_type(
        self,
        is_grounded: bool,
        summary: RetrievalSummary,
    ) -> ChatAnswerSourceType:
        if is_grounded:
            return ChatAnswerSourceType.rag
        if summary.reason == "NO_PROCESSED_MATERIAL":
            return ChatAnswerSourceType.no_material

        return ChatAnswerSourceType.general_llm

    def _apply_notice(self, answer: str, answer_source_type: ChatAnswerSourceType) -> str:
        body = answer.strip()
        if answer_source_type is ChatAnswerSourceType.general_llm:
            return f"{INSUFFICIENT_CONTEXT_NOTICE}\n\n{body}"
        if answer_source_type is ChatAnswerSourceType.no_material:
            return f"{NO_MATERIAL_NOTICE}\n\n{body}"

        return body

    def _persist(
        self,
        *,
        chat_session: ChatSession,
        user: User,
        course: Course,
        question: str,
        answer: str,
        sources: Sequence[AnswerSource],
        is_grounded: bool,
        answer_source_type: ChatAnswerSourceType,
        model_name: Optional[str],
        summary: RetrievalSummary,
        safety: SafetyResult,
        started: float,
    ) -> ChatAnswer:
        response_time_ms = int((perf_counter() - started) * 1000)
        log = ChatLog(
            session_id=chat_session.id,
            user_id=user.id,
            course_id=course.id,
            question=question,
            answer=answer,
            referenced_documents=[source.as_dict() for source in sources],
            model_name=model_name,
            response_time_ms=response_time_ms,
            is_grounded=is_grounded,
            answer_source_type=answer_source_type,
            safety_result=safety.as_dict(),
            retrieval_result=summary_to_dict(summary),
        )
        self.session.add(log)

        if not chat_session.title:
            chat_session.title = build_session_title(question)
        chat_session.updated_at = datetime.now(timezone.utc)

        self.session.commit()
        self.session.refresh(log)

        return ChatAnswer(
            session_id=chat_session.id,
            log_id=log.id,
            answer=answer,
            sources=list(sources),
            is_grounded=is_grounded,
            answer_source_type=answer_source_type.value,
            model_name=model_name,
            response_time_ms=response_time_ms,
            summary=summary,
            safety=safety,
        )


def build_sources(results: Sequence[SearchResult]) -> list[AnswerSource]:
    """Collapse duplicate document/page/chunk hits into one citation each."""

    seen: set = set()
    sources: list[AnswerSource] = []
    for result in results:
        key = (result.material_id, result.page_number, result.chunk_index)
        if key in seen:
            continue

        seen.add(key)
        sources.append(
            AnswerSource(
                material_id=result.material_id,
                document_name=result.document_name,
                page_number=result.page_number,
                chunk_index=result.chunk_index,
                score=round(result.score, 4),
            )
        )

    return sources


def build_session_title(question: str) -> str:
    collapsed = " ".join(question.split())
    if len(collapsed) <= TITLE_MAX_LENGTH:
        return collapsed

    return f"{collapsed[:TITLE_MAX_LENGTH]}…"


def summary_to_dict(summary: RetrievalSummary) -> dict:
    return {
        "top_k": summary.top_k,
        "result_count": summary.result_count,
        "max_score": summary.max_score,
        "score_threshold": summary.score_threshold,
        "search_mode": summary.search_mode,
        "embedding_model": summary.embedding_model,
        "total_candidate_chunks": summary.total_candidate_chunks,
        "reason": summary.reason,
    }
