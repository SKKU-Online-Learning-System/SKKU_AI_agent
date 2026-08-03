<<<<<<< HEAD
"""Course-scoped retrieval endpoints shared by the debug UI and answer generation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
=======
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session
>>>>>>> refs/remotes/origin/main

from app.api.deps import authorize_course_access, get_current_user, require_course_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
<<<<<<< HEAD
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
=======
from app.models import Course, CourseMaterial, CourseMaterialStatus, DocumentChunk, User, UserRole
from app.schemas import RAGSearchDebug, RAGSearchRequest, RAGSearchResponse, RAGStatusResponse
from app.services.rag_service import RAGService
>>>>>>> refs/remotes/origin/main

router = APIRouter(tags=["rag"])


<<<<<<< HEAD
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
            detail=f"RAG_SEARCH_FAILED: {exc}",
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
=======
@router.post(
    "/rag/search",
    response_model=RAGSearchResponse,
)
async def search_chunks(
    payload: RAGSearchRequest,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RAGSearchResponse:
    authorize_course_access(session, current_user, payload.course_id)
    if payload.debug and current_user.role == UserRole.student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Debug access denied")

    service = RAGService(session, settings)
    top_k = payload.top_k or service.settings.rag_top_k
    try:
        results = service.search(
            payload.course_id,
            payload.question,
            top_k,
        )
        debug = None
        if payload.debug:
            info = service.vector_store.get_search_debug_info(payload.course_id)
            debug = RAGSearchDebug(**info.__dict__)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "RAG_SEARCH_FAILED", "message": "RAG search failed"},
        ) from exc

    return RAGSearchResponse(
        course_id=payload.course_id,
        question=payload.question,
        top_k=top_k,
        results=results,
        debug=debug,
    )


@router.get("/courses/{course_id}/rag/status", response_model=RAGStatusResponse)
def get_rag_status(
    course: Annotated[Course, Depends(require_course_access)],
    session: Annotated[Session, Depends(get_db)],
) -> RAGStatusResponse:
    material_count, completed_count, failed_count = session.execute(
        select(
            func.count(CourseMaterial.id),
            func.sum(
                case(
                    (CourseMaterial.processing_status == CourseMaterialStatus.completed, 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (CourseMaterial.processing_status == CourseMaterialStatus.failed, 1),
                    else_=0,
                )
            ),
        ).where(CourseMaterial.course_id == course.id)
    ).one()
    chunk_count, embedded_count, searchable_count = session.execute(
        select(
            func.count(DocumentChunk.id),
            func.sum(case((DocumentChunk.embedding.is_not(None), 1), else_=0)),
            func.sum(
                case(
                    (
                        (DocumentChunk.embedding.is_not(None))
                        & (CourseMaterial.processing_status == CourseMaterialStatus.completed),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .select_from(DocumentChunk)
        .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
        .where(
            DocumentChunk.course_id == course.id,
            CourseMaterial.course_id == course.id,
        )
    ).one()

    return RAGStatusResponse(
        course_id=course.id,
        material_count=material_count,
        completed_material_count=completed_count or 0,
        failed_material_count=failed_count or 0,
        chunk_count=chunk_count,
        embedded_chunk_count=embedded_count or 0,
        is_search_ready=(searchable_count or 0) > 0,
>>>>>>> refs/remotes/origin/main
    )
