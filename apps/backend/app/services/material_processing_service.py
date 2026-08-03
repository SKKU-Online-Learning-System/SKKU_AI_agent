from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Protocol, Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import CourseMaterial, CourseMaterialStatus, DocumentChunk
from app.services.chunking_service import (
    ChunkingService,
    DocumentChunkInput,
    ParagraphChunkingService,
)
from app.services.document_parser_service import (
    DocumentParserService,
    FileDocumentParserService,
)
from app.services.embedding_service import (
    EmbeddingService,
    LocalHashEmbeddingService,
)
from app.services.vector_store_service import (
    SQLAlchemyLocalVectorStoreService,
    VectorStoreService,
)


class MaterialNotFoundError(Exception):
    pass


class MaterialProcessingConflictError(Exception):
    pass


class MaterialProcessingFailedError(Exception):
    pass


@dataclass(frozen=True)
class MaterialProcessingStatus:
    material_id: str
    processing_status: CourseMaterialStatus
    processing_error: Optional[str]
    chunk_count: int
    updated_at: datetime


class DocumentChunkRepository(Protocol):
    def clear_material(self, material_id: str) -> None:
        raise NotImplementedError

    def save(
        self,
        chunks: Sequence[DocumentChunkInput],
        embeddings: Sequence[list[float]],
        embedding_model: str,
    ) -> None:
        raise NotImplementedError

    def count(self, material_id: str) -> int:
        raise NotImplementedError


class SQLAlchemyDocumentChunkRepository:
    def __init__(
        self,
        session: Session,
        vector_store: Optional[VectorStoreService] = None,
    ) -> None:
        self.session = session
        self.vector_store = vector_store or SQLAlchemyLocalVectorStoreService(session)

    def clear_material(self, material_id: str) -> None:
        self.vector_store.delete_chunks_by_material(material_id)

    def save(
        self,
        chunks: Sequence[DocumentChunkInput],
        embeddings: Sequence[list[float]],
        embedding_model: str,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise MaterialProcessingFailedError("Embedding count does not match chunk count")
        stored_chunks = [
            DocumentChunk(
                course_id=chunk.course_id,
                material_id=chunk.material_id,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                char_count=chunk.char_count,
                embedding=embedding,
                embedding_model=embedding_model,
            )
            for chunk, embedding in zip(chunks, embeddings)
        ]
        self.vector_store.upsert_chunks(stored_chunks)

    def count(self, material_id: str) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.material_id == material_id)
            )
            or 0
        )


class MaterialProcessingService:
    def __init__(
        self,
        session: Session,
        parser: Optional[DocumentParserService] = None,
        chunker: Optional[ChunkingService] = None,
        embedder: Optional[EmbeddingService] = None,
        repository: Optional[DocumentChunkRepository] = None,
    ) -> None:
        self.session = session
        self.parser = parser or FileDocumentParserService()
        self.chunker = chunker or ParagraphChunkingService()
        self.embedder = embedder or LocalHashEmbeddingService()
        self.repository = repository or SQLAlchemyDocumentChunkRepository(session)

    def process_material(
        self,
        course_id: str,
        material_id: str,
        *,
        reprocess: bool = False,
    ) -> MaterialProcessingStatus:
        material = self._get_material(course_id, material_id)
        allowed_statuses = [CourseMaterialStatus.pending, CourseMaterialStatus.failed]
        if reprocess:
            allowed_statuses.append(CourseMaterialStatus.completed)

        claimed_id = self.session.execute(
            update(CourseMaterial)
            .where(
                CourseMaterial.id == material.id,
                CourseMaterial.course_id == course_id,
                CourseMaterial.processing_status.in_(allowed_statuses),
            )
            .values(
                processing_status=CourseMaterialStatus.processing,
                processing_error=None,
            )
            .returning(CourseMaterial.id)
        ).scalar_one_or_none()
        if claimed_id is None:
            self.session.rollback()
            current = self._get_material(course_id, material_id)
            raise MaterialProcessingConflictError(
                f"Material cannot be processed from status {current.processing_status.value}"
            )
        self.session.commit()

        try:
            material = self._get_material(course_id, material_id)
            self.repository.clear_material(material_id)
            self.session.commit()

            document = self.parser.parse(material)
            chunks = self.chunker.create_chunks(document)
            if not chunks:
                raise MaterialProcessingFailedError("Document produced no chunks")
            embeddings = self.embedder.embed_texts([chunk.chunk_text for chunk in chunks])
            self.repository.save(
                chunks,
                embeddings,
                self.embedder.model_name,
            )
            material.processing_status = CourseMaterialStatus.completed
            material.processing_error = None
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            error = str(exc).strip() or "Material processing failed"
            self.session.execute(
                update(CourseMaterial)
                .where(
                    CourseMaterial.id == material_id,
                    CourseMaterial.course_id == course_id,
                )
                .values(
                    processing_status=CourseMaterialStatus.failed,
                    processing_error=error[:1000],
                )
            )
            self.session.commit()
            if isinstance(exc, MaterialProcessingFailedError):
                raise
            raise MaterialProcessingFailedError(error) from exc

        return self.get_status(course_id, material_id)

    def get_status(self, course_id: str, material_id: str) -> MaterialProcessingStatus:
        material = self._get_material(course_id, material_id)
        return MaterialProcessingStatus(
            material_id=material.id,
            processing_status=material.processing_status,
            processing_error=material.processing_error,
            chunk_count=self.repository.count(material.id),
            updated_at=material.updated_at,
        )

    def _get_material(self, course_id: str, material_id: str) -> CourseMaterial:
        material = self.session.scalar(
            select(CourseMaterial).where(
                CourseMaterial.id == material_id,
                CourseMaterial.course_id == course_id,
            )
        )
        if material is None:
            raise MaterialNotFoundError
        return material
