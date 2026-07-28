from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import authorize_course_access, get_current_user, require_course_access
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import Course, CourseMaterial, CourseMaterialStatus, DocumentChunk, User, UserRole
from app.schemas import RAGSearchDebug, RAGSearchRequest, RAGSearchResponse, RAGStatusResponse
from app.services.rag_service import RAGService

router = APIRouter(tags=["rag"])


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
    )
