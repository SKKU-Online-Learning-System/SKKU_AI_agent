"""Course-scoped retrieval endpoints shared by the debug UI and answer generation."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import authorize_course_access, get_current_user, require_course_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import Course, User
from app.schemas import (
    CourseRagStatusRead,
    RagSearchDebugRead,
    RagSearchRequest,
    RagSearchResponse,
    RagSearchResultRead,
)
from app.services.embedding_service import EmbeddingError
from app.services.rag_service import RagService

router = APIRouter(tags=["rag"])
logger = logging.getLogger(__name__)


@router.post("/rag/search", response_model=RagSearchResponse)
async def search_course_documents(
    payload: RagSearchRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RagSearchResponse:
    question = payload.question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="질문을 입력해 주세요.",
        )

    course = authorize_course_access(session, current_user, payload.course_id)
    service = RagService(session, settings)
    try:
        # Embedding the question can call an external API, so keep it off the event loop.
        outcome = await run_in_threadpool(service.retrieve, course.id, question, payload.top_k)
    except EmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RAG_SEARCH_FAILED", "message": "Embedding unavailable"},
        ) from exc
    except Exception as exc:
        logger.exception("RAG search failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "RAG_SEARCH_FAILED", "message": "RAG search failed"},
        ) from exc

    return RagSearchResponse(
        course_id=course.id,
        question=question,
        top_k=outcome.summary.top_k,
        results=[
            RagSearchResultRead(
                chunk_id=result.chunk_id,
                material_id=result.material_id,
                document_name=result.document_name,
                page_number=result.page_number,
                chunk_index=result.chunk_index,
                chunk_text=result.chunk_text,
                score=result.score,
            )
            for result in outcome.results
        ],
        debug=RagSearchDebugRead(
            embedding_model=outcome.summary.embedding_model,
            search_mode=outcome.summary.search_mode,
            score_threshold=outcome.summary.score_threshold,
            total_candidate_chunks=outcome.summary.total_candidate_chunks,
        )
        if payload.debug
        else None,
    )


@router.get("/courses/{course_id}/rag/status", response_model=CourseRagStatusRead)
async def read_course_rag_status(
    course: Annotated[Course, Depends(require_course_access)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CourseRagStatusRead:
    status_value = RagService(session, settings).course_status(course.id)
    return CourseRagStatusRead(
        course_id=status_value.course_id,
        material_count=status_value.material_count,
        completed_material_count=status_value.completed_material_count,
        failed_material_count=status_value.failed_material_count,
        pending_material_count=status_value.pending_material_count,
        chunk_count=status_value.chunk_count,
        embedded_chunk_count=status_value.embedded_chunk_count,
        is_search_ready=status_value.is_search_ready,
    )
