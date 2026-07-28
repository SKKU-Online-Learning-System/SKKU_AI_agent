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
from app.services.material_service import MaterialValidationError, remove_stored_file, save_upload
from app.services.material_processing_service import (
    MaterialNotFoundError,
    MaterialProcessingConflictError,
    MaterialProcessingFailedError,
    MaterialProcessingService,
)
from app.services.embedding_service import create_embedding_service

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
        CourseMaterialRead.model_validate(material).model_copy(
            update={"chunk_count": chunk_count}
        )
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


def run_material_processing(
    session: Session,
    settings: Settings,
    course_id: str,
    material_id: str,
    *,
    reprocess: bool,
) -> MaterialProcessingStatusRead:
    service = MaterialProcessingService(
        session,
        embedder=create_embedding_service(settings),
    )
    try:
        result = service.process_material(
            course_id,
            material_id,
            reprocess=reprocess,
        )
    except MaterialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material not found",
        ) from exc
    except MaterialProcessingConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except MaterialProcessingFailedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return MaterialProcessingStatusRead.model_validate(result)


@router.post(
    "/courses/{course_id}/materials/{material_id}/process",
    response_model=MaterialProcessingStatusRead,
)
async def process_material(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialProcessingStatusRead:
    return run_material_processing(
        session,
        settings,
        course.id,
        material_id,
        reprocess=False,
    )


@router.post(
    "/courses/{course_id}/materials/{material_id}/reprocess",
    response_model=MaterialProcessingStatusRead,
)
async def reprocess_material(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MaterialProcessingStatusRead:
    return run_material_processing(
        session,
        settings,
        course.id,
        material_id,
        reprocess=True,
    )


@router.get(
    "/courses/{course_id}/materials/{material_id}/processing-status",
    response_model=MaterialProcessingStatusRead,
)
async def get_material_processing_status(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> MaterialProcessingStatusRead:
    try:
        result = MaterialProcessingService(session).get_status(course.id, material_id)
    except MaterialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material not found",
        ) from exc
    return MaterialProcessingStatusRead.model_validate(result)


@router.get("/courses/{course_id}/materials/{material_id}/download")
async def download_material(
    course: Annotated[Course, Depends(require_course_access)],
    material_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    material = session.scalar(
        select(CourseMaterial).where(
            CourseMaterial.id == material_id,
            CourseMaterial.course_id == course.id,
        )
    )
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material not found")
    if not Path(material.storage_path).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material file not found")
    return FileResponse(
        material.storage_path,
        filename=material.original_file_name,
        media_type="application/octet-stream",
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
