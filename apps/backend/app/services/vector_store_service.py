<<<<<<< HEAD
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
from app.models import CourseMaterial, DocumentChunk
from app.services.chunking_service import DocumentChunkInput
from app.services.embedding_service import cosine_similarity
=======
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
>>>>>>> refs/remotes/origin/main


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    course_id: str
    material_id: str
<<<<<<< HEAD
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
=======
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
>>>>>>> refs/remotes/origin/main

    def delete_chunks_by_material(self, material_id: str) -> None:
        self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.material_id == material_id)
        )

<<<<<<< HEAD
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

=======
>>>>>>> refs/remotes/origin/main
    def search_similar_chunks(
        self,
        course_id: str,
        query_embedding: Sequence[float],
<<<<<<< HEAD
        top_k: int = 5,
        score_threshold: Optional[float] = None,
    ) -> list[SearchResult]:
        """Rank the course's embedded chunks; other courses are never considered."""

        if self.settings.vector_search_mode != "local":
            raise NotImplementedError(
                "VECTOR_SEARCH_MODE=pgvector는 아직 구현되지 않았습니다. local 모드를 사용하세요."
            )

        bounded_top_k = max(1, min(top_k, self.settings.rag_max_top_k))
=======
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

>>>>>>> refs/remotes/origin/main
        rows = self.session.execute(
            select(DocumentChunk, CourseMaterial.original_file_name)
            .join(CourseMaterial, CourseMaterial.id == DocumentChunk.material_id)
            .where(
                DocumentChunk.course_id == course_id,
<<<<<<< HEAD
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
        ]

        if score_threshold is not None:
            results = [result for result in results if result.score >= score_threshold]

        results.sort(key=lambda result: result.score, reverse=True)
        return results[:bounded_top_k]

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
=======
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
>>>>>>> refs/remotes/origin/main
