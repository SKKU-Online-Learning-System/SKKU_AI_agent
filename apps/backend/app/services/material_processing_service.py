<<<<<<< HEAD
"""Turn an uploaded material into embedded, searchable chunks.

The whole run is a single `process_material(material_id)` call so it can later
move to a background worker without changing the API contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import CourseMaterial, CourseMaterialStatus
from app.services.chunking_service import create_chunks
from app.services.document_parser import DocumentParseError, parse_material
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)

RESTARTABLE_STATUSES = (
    CourseMaterialStatus.pending,
    CourseMaterialStatus.failed,
)
REPROCESSABLE_STATUSES = RESTARTABLE_STATUSES + (CourseMaterialStatus.completed,)


class MaterialNotFoundError(Exception):
    code = "MATERIAL_NOT_FOUND"


class MaterialAlreadyProcessingError(Exception):
    code = "MATERIAL_ALREADY_PROCESSING"


class MaterialProcessingError(Exception):
    """Raised when a run fails after the material was already marked processing."""

    def __init__(self, message: str, code: str = "MATERIAL_PROCESSING_FAILED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProcessingOutcome:
    material_id: str
    processing_status: str
    chunk_count: int
    embedding_model: str
=======
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
>>>>>>> refs/remotes/origin/main


class MaterialProcessingService:
    def __init__(
        self,
        session: Session,
<<<<<<< HEAD
        settings: Settings,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStoreService] = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.embedding_service = embedding_service or EmbeddingService(settings)
        self.vector_store = vector_store or VectorStoreService(session, settings)

    def process_material(self, material_id: str, *, reprocess: bool = False) -> ProcessingOutcome:
        material = self.session.get(CourseMaterial, material_id)
        if material is None:
            raise MaterialNotFoundError("자료를 찾을 수 없습니다.")

        self._claim(material, reprocess=reprocess)

        try:
            outcome = self._run_pipeline(material)
        except (DocumentParseError, EmbeddingError) as error:
            self._mark_failed(material, getattr(error, "code", "MATERIAL_PROCESSING_FAILED"), error)
            raise MaterialProcessingError(str(error), getattr(error, "code", None) or "") from error
        except Exception as error:
            self._mark_failed(material, "MATERIAL_PROCESSING_FAILED", error)
            raise MaterialProcessingError(
                "자료를 처리하는 중 오류가 발생했습니다."
            ) from error

        return outcome

    def _claim(self, material: CourseMaterial, *, reprocess: bool) -> None:
        """Flip the row to `processing` only if nobody else already did."""

        allowed = REPROCESSABLE_STATUSES if reprocess else RESTARTABLE_STATUSES
        result = self.session.execute(
            update(CourseMaterial)
            .where(
                CourseMaterial.id == material.id,
                CourseMaterial.processing_status.in_(allowed),
=======
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
>>>>>>> refs/remotes/origin/main
            )
            .values(
                processing_status=CourseMaterialStatus.processing,
                processing_error=None,
            )
<<<<<<< HEAD
        )
        if result.rowcount == 0:
            self.session.rollback()
            raise MaterialAlreadyProcessingError(
                "이미 처리 중이거나 현재 상태에서는 처리할 수 없는 자료입니다."
            )

        self.session.commit()
        self.session.refresh(material)

    def _run_pipeline(self, material: CourseMaterial) -> ProcessingOutcome:
        document = parse_material(
            material_id=material.id,
            course_id=material.course_id,
            title=material.original_file_name,
            storage_path=material.storage_path,
        )
        chunks = create_chunks(
            document,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
            min_chunk_chars=self.settings.min_chunk_chars,
        )
        if not chunks:
            raise MaterialProcessingError(
                "문서에서 저장할 수 있는 청크를 만들지 못했습니다.",
                "DOCUMENT_TEXT_NOT_FOUND",
            )

        embeddings = self.embedding_service.embed_texts([chunk.chunk_text for chunk in chunks])
        embedding_model = self.embedding_service.model_name
        self.vector_store.replace_material_chunks(
            course_id=material.course_id,
            material_id=material.id,
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=embedding_model,
        )

        material.processing_status = CourseMaterialStatus.completed
        material.processing_error = None
        self.session.commit()
        logger.info(
            "Processed material %s into %d chunk(s) with %s",
            material.id,
            len(chunks),
            embedding_model,
        )

        return ProcessingOutcome(
            material_id=material.id,
            processing_status=CourseMaterialStatus.completed.value,
            chunk_count=len(chunks),
            embedding_model=embedding_model,
        )

    def _mark_failed(self, material: CourseMaterial, code: str, error: Exception) -> None:
        """Never leave a material stuck in `processing`."""

        self.session.rollback()
        self.session.execute(
            update(CourseMaterial)
            .where(CourseMaterial.id == material.id)
            .values(
                processing_status=CourseMaterialStatus.failed,
                processing_error=f"[{code}] {error}"[:2000],
            )
        )
        self.session.commit()
        logger.warning("Material %s processing failed (%s): %s", material.id, code, error)
=======
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
>>>>>>> refs/remotes/origin/main
