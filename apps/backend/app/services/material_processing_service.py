"""Turn an uploaded material into embedded, searchable chunks.

The whole run is a single `process_material(material_id)` call so it can later
move to a background worker without changing the API contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import CourseMaterial, CourseMaterialStatus
from app.services.chunking_service import create_chunks
from app.services.document_parser import DocumentParseError, parse_material
from app.services.document_parser_service import DocumentParserService
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


class MaterialProcessingService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStoreService] = None,
        parser: Optional[DocumentParserService] = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.embedding_service = embedding_service or EmbeddingService(self.settings)
        self.vector_store = vector_store or VectorStoreService(session, self.settings)
        self.parser = parser

    def process_material(
        self,
        material_or_course_id: str,
        material_id: Optional[str] = None,
        *,
        reprocess: bool = False,
    ) -> ProcessingOutcome:
        if material_id is None:
            material = self.session.get(CourseMaterial, material_or_course_id)
        else:
            material = self.session.scalar(
                select(CourseMaterial).where(
                    CourseMaterial.id == material_id,
                    CourseMaterial.course_id == material_or_course_id,
                )
            )
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
            )
            .values(
                processing_status=CourseMaterialStatus.processing,
                processing_error=None,
            )
        )
        if result.rowcount == 0:
            self.session.rollback()
            raise MaterialAlreadyProcessingError(
                "이미 처리 중이거나 현재 상태에서는 처리할 수 없는 자료입니다."
            )

        self.session.commit()
        self.session.refresh(material)

    def _run_pipeline(self, material: CourseMaterial) -> ProcessingOutcome:
        if self.parser is not None:
            document = self.parser.parse(material)
        else:
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
                processing_error=f"{code}: {error}"[:2000],
            )
        )
        self.session.commit()
        logger.warning("Material %s processing failed (%s): %s", material.id, code, error)
