from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    require_course_access,
    require_course_manage_permission,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import Course, CourseMaterial, CourseMaterialStatus, User
from app.schemas import CourseMaterialRead
from app.services.material_service import MaterialValidationError, remove_stored_file, save_upload

router = APIRouter(tags=["materials"])


@router.get("/courses/{course_id}/materials", response_model=list[CourseMaterialRead])
async def list_materials(
    course: Annotated[Course, Depends(require_course_access)],
    session: Annotated[Session, Depends(get_db)],
) -> list[CourseMaterialRead]:
    return list(
        session.scalars(
            select(CourseMaterial)
            .where(CourseMaterial.course_id == course.id)
            .order_by(CourseMaterial.created_at)
        )
    )


@router.post(
    "/courses/{course_id}/materials",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_material(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: UploadFile = File(...),
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
        storage_path=str(stored.storage_path),
        processing_status=CourseMaterialStatus.pending,
    )
    session.add(material)
    try:
        session.commit()
        session.refresh(material)
    except Exception:
        session.rollback()
        remove_stored_file(stored.storage_path)
        raise
    return material


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
    remove_stored_file(storage_path)
