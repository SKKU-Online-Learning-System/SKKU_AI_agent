"""Course-scoped storage and similarity search over document chunks.

MVP note: `local` mode reads the stored vectors and ranks them in the
application. It is intentionally simple and meant for development-sized data;
swapping in pgvector only requires replacing this service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CourseMaterial, CourseMaterialStatus, DocumentChunk
from app.services.chunking_service import DocumentChunkInput
from app.services.embedding_service import cosine_similarity


class VectorSearchError(Exception):
    code = "VECTOR_SEARCH_FAILED"


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    course_id: str
    material_id: str
    document_name: str
    chunk_index: int
    page_number: Optional[int]
    chunk_text: str
    score: float


@dataclass(frozen=True)
class CourseChunkStats:
    chunk_count: int
    embedded_chunk_count: int


class VectorStoreService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def delete_chunks_by_material(self, material_id: str) -> None:
        self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.material_id == material_id)
        )

    def replace_material_chunks(
        self,
        *,
        course_id: str,
        material_id: str,
        chunks: Sequence[DocumentChunkInput],
        embeddings: Sequence[Sequence[float]],
        embedding_model: str,
    ) -> list[DocumentChunk]:
        """Drop any previous chunks for the material, then store the new ones."""

        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")

        self.delete_chunks_by_material(material_id)
        self.session.flush()

        embedded_at = datetime.now(timezone.utc)
        records = [
            DocumentChunk(
                course_id=course_id,
                material_id=material_id,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                char_count=chunk.char_count,
                embedding=list(embedding),
                embedding_model=embedding_model,
                embedded_at=embedded_at,
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        self.session.add_all(records)
        self.session.flush()
        return records

    def search_similar_chunks(
        self,
        course_id: str,
        query_embedding: Sequence[float],
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[SearchResult]:
        """Rank the course's embedded chunks; other courses are never considered."""

        if self.settings.vector_search_mode != "local":
            raise NotImplementedError(
                "VECTOR_SEARCH_MODE=pgvector는 아직 구현되지 않았습니다. local 모드를 사용하세요."
            )

        bounded_top_k = max(1, min(top_k, self.settings.rag_max_top_k))
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

        results = [
            SearchResult(
                chunk_id=chunk.id,
                course_id=chunk.course_id,
                material_id=chunk.material_id,
                document_name=document_name,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                chunk_text=chunk.chunk_text,
                score=cosine_similarity(query_embedding, chunk.embedding or []),
            )
            for chunk, document_name in rows
            if len(chunk.embedding or []) == len(query_embedding)
        ]

        if score_threshold is not None:
            results = [result for result in results if result.score >= score_threshold]

        results.sort(key=lambda result: result.score, reverse=True)
        return results[:bounded_top_k]

    def count_searchable_chunks(self, course_id: str) -> int:
        total = self.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
            .where(
                DocumentChunk.course_id == course_id,
                CourseMaterial.course_id == course_id,
                CourseMaterial.processing_status == CourseMaterialStatus.completed,
                DocumentChunk.embedding.is_not(None),
            )
        )
        return int(total or 0)

    def count_course_chunks(self, course_id: str) -> CourseChunkStats:
        chunk_count = self.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.course_id == course_id)
        )
        embedded_count = self.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.course_id == course_id,
                DocumentChunk.embedding.is_not(None),
            )
        )
        return CourseChunkStats(
            chunk_count=int(chunk_count or 0),
            embedded_chunk_count=int(embedded_count or 0),
        )

    def count_material_chunks(self, material_id: str) -> int:
        total = self.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.material_id == material_id)
        )
        return int(total or 0)


class SQLAlchemyLocalVectorStoreService:
    """Backward-compatible repository API used by the original regression suite."""

    def __init__(
        self,
        session: Session,
        *,
        score_threshold: float = 0.0,
        max_top_k: int = 20,
    ) -> None:
        self.session = session
        self.score_threshold = score_threshold
        self.max_top_k = max_top_k

    def upsert_chunks(self, chunks: Sequence[DocumentChunk]) -> None:
        for chunk in chunks:
            self.session.merge(chunk)
        self.session.flush()

    def delete_chunks_by_material(self, material_id: str) -> None:
        self.session.execute(delete(DocumentChunk).where(DocumentChunk.material_id == material_id))

    def search_similar_chunks(
        self,
        course_id: str,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
    ) -> list[SearchResult]:
        if top_k < 1 or top_k > self.max_top_k:
            raise VectorSearchError("VECTOR_TOP_K_INVALID")
        rows = self.session.execute(
            select(DocumentChunk, CourseMaterial.original_file_name)
            .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
            .where(
                DocumentChunk.course_id == course_id,
                CourseMaterial.course_id == course_id,
                DocumentChunk.embedding.is_not(None),
            )
        ).all()
        results: list[SearchResult] = []
        for chunk, document_name in rows:
            embedding = chunk.embedding or []
            if len(embedding) != len(query_embedding):
                continue
            score = cosine_similarity(query_embedding, embedding)
            if score < self.score_threshold:
                continue
            results.append(
                SearchResult(
                    chunk_id=chunk.id,
                    course_id=chunk.course_id,
                    material_id=chunk.material_id,
                    document_name=document_name,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    chunk_text=chunk.chunk_text,
                    score=score,
                )
            )
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:top_k]


def create_vector_store_service(
    session: Session,
    settings: Settings,
) -> SQLAlchemyLocalVectorStoreService:
    if settings.vector_search_mode != "local":
        raise VectorSearchError("VECTOR_SEARCH_MODE_UNAVAILABLE")
    return SQLAlchemyLocalVectorStoreService(
        session,
        score_threshold=settings.rag_score_threshold,
        max_top_k=settings.rag_max_top_k,
    )
