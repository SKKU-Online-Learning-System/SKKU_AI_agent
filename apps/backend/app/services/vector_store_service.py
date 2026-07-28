from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CourseMaterial, CourseMaterialStatus, DocumentChunk

MAX_TOP_K = 20


class VectorSearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    course_id: str
    material_id: str
    chunk_index: int
    chunk_text: str
    page_number: Optional[int]
    score: float
    document_name: str


@dataclass(frozen=True)
class SearchDebugInfo:
    embedding_model: Optional[str]
    search_mode: str
    score_threshold: Optional[float]
    total_candidate_chunks: int


class VectorStoreService(Protocol):
    def upsert_chunks(self, chunks: Sequence[DocumentChunk]) -> None:
        raise NotImplementedError

    def delete_chunks_by_material(self, material_id: str) -> None:
        raise NotImplementedError

    def search_similar_chunks(
        self,
        course_id: str,
        query_embedding: Sequence[float],
        top_k: Optional[int] = None,
    ) -> list[SearchResult]:
        raise NotImplementedError

    def get_search_debug_info(self, course_id: str) -> SearchDebugInfo:
        raise NotImplementedError


class SQLAlchemyLocalVectorStoreService:
    """MVP search that scores only course-filtered DB rows in application memory.

    Replace this implementation with pgvector when embedding becomes a native vector column.
    """

    def __init__(
        self,
        session: Session,
        *,
        default_top_k: int = 5,
        score_threshold: float = 0.3,
        max_top_k: int = MAX_TOP_K,
    ) -> None:
        if default_top_k < 1 or default_top_k > max_top_k:
            raise ValueError("default_top_k must be between 1 and max_top_k")
        if score_threshold < -1 or score_threshold > 1:
            raise ValueError("score_threshold must be between -1 and 1")
        self.session = session
        self.default_top_k = default_top_k
        self.score_threshold = score_threshold
        self.max_top_k = max_top_k

    def upsert_chunks(self, chunks: Sequence[DocumentChunk]) -> None:
        for chunk in chunks:
            self.session.merge(chunk)
        self.session.flush()

    def delete_chunks_by_material(self, material_id: str) -> None:
        self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.material_id == material_id)
        )

    def search_similar_chunks(
        self,
        course_id: str,
        query_embedding: Sequence[float],
        top_k: Optional[int] = None,
    ) -> list[SearchResult]:
        limit = self.default_top_k if top_k is None else top_k
        if limit < 1 or limit > self.max_top_k:
            raise VectorSearchError(
                f"VECTOR_TOP_K_INVALID: top_k must be between 1 and {self.max_top_k}"
            )
        if not query_embedding:
            raise VectorSearchError(
                "VECTOR_QUERY_EMBEDDING_EMPTY: Query embedding must not be empty"
            )

        rows = self.session.execute(
            select(DocumentChunk, CourseMaterial.original_file_name)
            .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
            .where(
                DocumentChunk.course_id == course_id,
                CourseMaterial.course_id == course_id,
                CourseMaterial.processing_status == CourseMaterialStatus.completed,
                DocumentChunk.embedding.is_not(None),
            )
        ).all()
        results: list[SearchResult] = []
        for chunk, document_name in rows:
            embedding = chunk.embedding
            if not embedding or len(embedding) != len(query_embedding):
                continue
            score = cosine_similarity(query_embedding, embedding)
            if score < self.score_threshold:
                continue
            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    course_id=chunk.course_id,
                    material_id=chunk.material_id,
                    chunk_index=chunk.chunk_index,
                    chunk_text=chunk.chunk_text,
                    page_number=chunk.page_number,
                    score=score,
                    document_name=document_name,
                )
            )
        return sorted(results, key=lambda item: (-item.score, item.chunk_id))[:limit]

    def get_search_debug_info(self, course_id: str) -> SearchDebugInfo:
        candidate_count, model_count, model = self.session.execute(
            select(
                func.count(DocumentChunk.id),
                func.count(distinct(DocumentChunk.embedding_model)),
                func.min(DocumentChunk.embedding_model),
            )
            .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
            .where(
                DocumentChunk.course_id == course_id,
                CourseMaterial.course_id == course_id,
                CourseMaterial.processing_status == CourseMaterialStatus.completed,
                DocumentChunk.embedding.is_not(None),
            )
        ).one()
        return SearchDebugInfo(
            embedding_model="mixed" if model_count > 1 else model,
            search_mode="local",
            score_threshold=self.score_threshold,
            total_candidate_chunks=candidate_count,
        )


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def create_vector_store_service(
    session: Session,
    settings: Settings,
) -> VectorStoreService:
    if settings.vector_search_mode == "local":
        return SQLAlchemyLocalVectorStoreService(
            session,
            default_top_k=settings.rag_top_k,
            score_threshold=settings.rag_score_threshold,
        )
    raise VectorSearchError(
        "VECTOR_SEARCH_MODE_UNAVAILABLE: pgvector requires a native vector column"
    )
