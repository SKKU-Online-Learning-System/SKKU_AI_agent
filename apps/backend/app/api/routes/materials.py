import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    get_current_user,
    require_course_access,
    require_course_manage_permission,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import Course, CourseMaterial, CourseMaterialStatus, DocumentChunk, User
from app.schemas import CourseMaterialRead, MaterialProcessingStatusRead
from app.services.material_processing_service import (
    MaterialAlreadyProcessingError,
    MaterialNotFoundError,
    MaterialProcessingError,
    MaterialProcessingService,
)
from app.services.material_service import MaterialValidationError, remove_stored_file, save_upload
from app.services.vector_store_service import VectorStoreService

router = APIRouter(tags=["materials"])
logger = logging.getLogger(__name__)


@router.get("/courses/{course_id}/materials", response_model=list[CourseMaterialRead])
async def list_materials(
    course: Annotated[Course, Depends(require_course_access)],
    session: Annotated[Session, Depends(get_db)],
) -> list[CourseMaterialRead]:
    rows = session.execute(
        select(CourseMaterial, func.count(DocumentChunk.id))
        .outerjoin(DocumentChunk, DocumentChunk.material_id == CourseMaterial.id)
        .where(CourseMaterial.course_id == course.id)
        .group_by(CourseMaterial.id)
        .order_by(CourseMaterial.created_at.desc())
    )
    return [
        CourseMaterialRead.model_validate(material).model_copy(update={"chunk_count": chunk_count})
        for material, chunk_count in rows
    ]


@router.post(
    "/courses/{course_id}/materials",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_material(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
    week: Annotated[int, Form(ge=1, le=16)] = 1,
) -> CourseMaterialRead:
    try:
        stored = await save_upload(
            file,
            course.id,
            settings.upload_dir,
            settings.max_upload_size_bytes,
        )
    except MaterialValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    material = CourseMaterial(
        course_id=course.id,
        uploaded_by=current_user.id,
        file_name=stored.internal_file_name,
        original_file_name=stored.original_file_name,
        file_type=stored.file_type,
        file_size=stored.file_size,
        week=week,
        storage_path=str(stored.storage_path),
        processing_status=CourseMaterialStatus.pending,
    )
    session.add(material)
    try:
        session.flush()
        session.refresh(material)
        response = CourseMaterialRead.model_validate(material)
        session.commit()
    except Exception:
        session.rollback()
        await run_in_threadpool(remove_stored_file, stored.storage_path)
        raise
    return response


def _load_course_material(session: Session, course_id: str, material_id: str) -> CourseMaterial:
    material = session.scalar(
        select(CourseMaterial).where(
            CourseMaterial.id == material_id,
            CourseMaterial.course_id == course_id,
        )
    )
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found")

    return material


def _processing_status_response(
    session: Session,
    settings: Settings,
    material: CourseMaterial,
) -> MaterialProcessingStatusRead:
    store = VectorStoreService(session, settings)
    status_value = getattr(material.processing_status, "value", material.processing_status)
    embedding_model = session.scalar(
        select(DocumentChunk.embedding_model)
        .where(DocumentChunk.material_id == material.id)
        .limit(1)
    )

    return MaterialProcessingStatusRead(
        material_id=material.id,
        processing_status=status_value,
        processing_error=material.processing_error,
        chunk_count=store.count_material_chunks(material.id),
        embedding_model=embedding_model,
        updated_at=material.updated_at,
    )


def _run_processing(
    session: Session,
    settings: Settings,
    material: CourseMaterial,
    *,
    reprocess: bool,
) -> MaterialProcessingStatusRead:
    service = MaterialProcessingService(session, settings)
    try:
        service.process_material(material.id, reprocess=reprocess)
    except MaterialNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MaterialAlreadyProcessingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MaterialProcessingError as exc:
        session.refresh(material)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    session.refresh(material)
    return _processing_status_response(session, settings, material)


@router.post(
    "/courses/{course_id}/materials/{material_id}/process",
    response_model=MaterialProcessingStatusRead,
)
async def process_material_route(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialProcessingStatusRead:
    material = _load_course_material(session, course.id, material_id)
    return await run_in_threadpool(
        _run_processing,
        session,
        settings,
        material,
        reprocess=False,
    )


@router.post(
    "/courses/{course_id}/materials/{material_id}/reprocess",
    response_model=MaterialProcessingStatusRead,
)
async def reprocess_material_route(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialProcessingStatusRead:
    material = _load_course_material(session, course.id, material_id)
    return await run_in_threadpool(
        _run_processing,
        session,
        settings,
        material,
        reprocess=True,
    )


@router.get(
    "/courses/{course_id}/materials/{material_id}/processing-status",
    response_model=MaterialProcessingStatusRead,
)
async def read_material_processing_status(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialProcessingStatusRead:
    material = _load_course_material(session, course.id, material_id)
    return _processing_status_response(session, settings, material)


@router.get("/courses/{course_id}/materials/{material_id}/download")
async def download_material(
    course: Annotated[Course, Depends(require_course_access)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    material = _load_course_material(session, course.id, material_id)
    path = Path(material.storage_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Material file not found")
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=material.original_file_name,
    )


@router.get("/courses/{course_id}/materials/{material_id}/content")
async def read_material_content(
    course: Annotated[Course, Depends(require_course_access)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    """Serve an authorized course PDF inline for KINGO's page visualization."""
    material = _load_course_material(session, course.id, material_id)
    if material.file_type.lower() != "pdf":
        raise HTTPException(status_code=422, detail="Only PDF materials can be previewed")
    path = Path(material.storage_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Material file not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=material.original_file_name,
        content_disposition_type="inline",
    )


@router.delete(
    "/courses/{course_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_material(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> None:
    material = session.scalar(
        select(CourseMaterial).where(
            CourseMaterial.id == material_id,
            CourseMaterial.course_id == course.id,
        )
    )
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found")

    storage_path = material.storage_path
    session.delete(material)
    session.commit()
    try:
        await run_in_threadpool(remove_stored_file, storage_path)
    except OSError:
        logger.exception(
            "Material file cleanup failed after database delete: material_id=%s storage_path=%s",
            material_id,
            storage_path,
        )
