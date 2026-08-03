<<<<<<< HEAD
"""Course-scoped retrieval used by the search API and by answer generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CourseMaterial, CourseMaterialStatus
from app.services.embedding_service import EmbeddingService
from app.services.vector_store_service import SearchResult, VectorStoreService
=======
from time import perf_counter
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.schemas import ChatResponse, RAGSearchResult
from app.services.embedding_service import create_embedding_service
from app.services.vector_store_service import VectorStoreService, create_vector_store_service


class RAGSearchError(Exception):
    pass
>>>>>>> refs/remotes/origin/main


@dataclass(frozen=True)
class RetrievalSummary:
    result_count: int
    max_score: Optional[float]
    score_threshold: float
    top_k: int
    search_mode: str
    embedding_model: str
    total_candidate_chunks: int
    reason: Optional[str] = None

<<<<<<< HEAD
=======
    def __init__(
        self,
        session: Optional[Session] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_store: Optional[VectorStoreService] = (
            create_vector_store_service(session, self.settings) if session else None
        )

    def search(self, course_id: str, question: str, top_k: int) -> list[RAGSearchResult]:
        if self.vector_store is None:
            raise RAGSearchError("RAG search requires a database session")
        try:
            query_embedding = create_embedding_service(self.settings).embed_text(question)
            return [
                RAGSearchResult(**result.__dict__)
                for result in self.vector_store.search_similar_chunks(
                    course_id,
                    query_embedding,
                    top_k,
                )
            ]
        except Exception as exc:
            raise RAGSearchError("RAG search failed") from exc
>>>>>>> refs/remotes/origin/main

@dataclass(frozen=True)
class RetrievalOutcome:
    summary: RetrievalSummary
    results: list[SearchResult] = field(default_factory=list)


@dataclass(frozen=True)
class CourseRagStatus:
    course_id: str
    material_count: int
    completed_material_count: int
    failed_material_count: int
    pending_material_count: int
    chunk_count: int
    embedded_chunk_count: int
    is_search_ready: bool


class RagService:
    """Embeds a question and returns the closest chunks inside one course."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStoreService] = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedding_service = embedding_service or EmbeddingService(settings)
        self.vector_store = vector_store or VectorStoreService(session, settings)

    def resolve_top_k(self, requested: Optional[int]) -> int:
        if requested is None:
            return self.settings.rag_top_k
        return max(1, min(requested, self.settings.rag_max_top_k))

    def retrieve(self, course_id: str, question: str, top_k: Optional[int] = None) -> RetrievalOutcome:
        resolved_top_k = self.resolve_top_k(top_k)
        stats = self.vector_store.count_course_chunks(course_id)
        threshold = self.settings.rag_score_threshold

        if stats.embedded_chunk_count == 0:
            return RetrievalOutcome(
                results=[],
                summary=RetrievalSummary(
                    result_count=0,
                    max_score=None,
                    score_threshold=threshold,
                    top_k=resolved_top_k,
                    search_mode=self.settings.vector_search_mode,
                    embedding_model=self.embedding_service.model_name,
                    total_candidate_chunks=0,
                    reason="NO_PROCESSED_MATERIAL",
                ),
            )

        query_embedding = self.embedding_service.embed_text(question)
        results = self.vector_store.search_similar_chunks(
            course_id=course_id,
            query_embedding=query_embedding,
            top_k=resolved_top_k,
            score_threshold=threshold,
        )
        max_score = max((result.score for result in results), default=None)

        return RetrievalOutcome(
            results=results,
            summary=RetrievalSummary(
                result_count=len(results),
                max_score=max_score,
                score_threshold=threshold,
                top_k=resolved_top_k,
                search_mode=self.settings.vector_search_mode,
                embedding_model=self.embedding_service.model_name,
                total_candidate_chunks=stats.embedded_chunk_count,
                reason=None if results else "NO_RELEVANT_CONTEXT",
            ),
        )

    def course_status(self, course_id: str) -> CourseRagStatus:
        counts = dict(
            self.session.execute(
                select(CourseMaterial.processing_status, func.count())
                .where(CourseMaterial.course_id == course_id)
                .group_by(CourseMaterial.processing_status)
            ).all()
        )
        stats = self.vector_store.count_course_chunks(course_id)

        def count_for(status: CourseMaterialStatus) -> int:
            return int(counts.get(status, counts.get(status.value, 0)) or 0)

        completed = count_for(CourseMaterialStatus.completed)
        return CourseRagStatus(
            course_id=course_id,
            material_count=sum(int(value or 0) for value in counts.values()),
            completed_material_count=completed,
            failed_material_count=count_for(CourseMaterialStatus.failed),
            pending_material_count=count_for(CourseMaterialStatus.pending),
            chunk_count=stats.chunk_count,
            embedded_chunk_count=stats.embedded_chunk_count,
            is_search_ready=completed > 0 and stats.embedded_chunk_count > 0,
        )
