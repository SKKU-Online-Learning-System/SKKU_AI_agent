"""Course-scoped retrieval used by the search API and by answer generation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CourseMaterial, CourseMaterialStatus, DocumentChunk
from app.services.embedding_service import EmbeddingService
from app.services.document_rendering import image_data_url
from app.services.llm_service import LLMService, LLMError
from app.services.vector_store_service import SearchResult, VectorStoreService


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
        searchable_count = self.vector_store.count_searchable_chunks(
            course_id, embedding_model=self.embedding_service.model_name,
        )
        threshold = self.settings.rag_score_threshold

        if searchable_count == 0:
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
                    reason=("REINDEX_REQUIRED" if self.vector_store.count_searchable_chunks(course_id)
                            else "NO_PROCESSED_MATERIAL"),
                ),
            )

        query_embedding = self.embedding_service.embed_text(question)
        results = self.vector_store.search_similar_chunks(
            course_id=course_id,
            query_embedding=query_embedding,
            top_k=resolved_top_k,
            score_threshold=threshold,
            text_score_threshold=self.settings.rag_text_score_threshold,
            embedding_model=self.embedding_service.model_name,
        )
        # The image and its question-independent reading are published atomically
        # at ingestion. Legacy chunks without a reading still need reindexing.
        grounded_results = []
        visual_count = 0
        for result in results:
            if result.has_image:
                if visual_count >= self.settings.rag_visual_max_pages:
                    continue
                evidence = result.page_evidence
                if not evidence:
                    image = self.session.scalar(select(DocumentChunk.page_image).where(
                        DocumentChunk.id == result.chunk_id,
                        DocumentChunk.course_id == course_id,
                    ))
                    if not image:
                        raise LLMError("검색된 페이지의 원본 이미지가 없습니다.")
                    evidence = LLMService(self.settings).read_document_image(
                        image_data_url(image), question,
                    )
                result = replace(result, chunk_text=(
                    f"[원본 페이지 이미지 판독]\n{evidence}\n\n"
                    f"[문서 원문 텍스트]\n{result.chunk_text}"
                ))
                visual_count += 1
            grounded_results.append(result)
        results = grounded_results
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
                total_candidate_chunks=searchable_count,
                reason=None if results else "NO_RELEVANT_CONTEXT",
            ),
        )

    def inspect_page(self, course_id: str, material_id: str, page_number: int, question: str) -> str:
        """Read missing detail on demand, scoped to an existing completed source."""
        if not question.strip() or type(page_number) is not int or page_number < 1:
            raise ValueError("A page number and a specific missing detail are required")
        image = self.session.scalar(
            select(DocumentChunk.page_image)
            .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
            .where(
                DocumentChunk.course_id == course_id,
                CourseMaterial.course_id == course_id,
                CourseMaterial.id == material_id,
                CourseMaterial.processing_status == CourseMaterialStatus.completed,
                DocumentChunk.page_number == page_number,
                DocumentChunk.page_image.is_not(None),
            ).limit(1)
        )
        if not image:
            raise ValueError("Completed source page not found in this course")
        return LLMService(self.settings).read_document_image(image_data_url(image), question)

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
        searchable_count = self.vector_store.count_searchable_chunks(
            course_id, embedding_model=self.embedding_service.model_name,
        )
        return CourseRagStatus(
            course_id=course_id,
            material_count=sum(int(value or 0) for value in counts.values()),
            completed_material_count=completed,
            failed_material_count=count_for(CourseMaterialStatus.failed),
            pending_material_count=count_for(CourseMaterialStatus.pending),
            chunk_count=stats.chunk_count,
            embedded_chunk_count=stats.embedded_chunk_count,
            is_search_ready=completed > 0 and searchable_count > 0,
        )
