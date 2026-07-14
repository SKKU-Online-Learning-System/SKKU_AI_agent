from datetime import datetime, timezone
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import (
    get_current_user,
    require_course_access,
    require_course_manage_permission,
)
from app.models import Course, User
from app.schemas import CourseMaterialRead

router = APIRouter(tags=["materials"])


@router.get("/courses/{course_id}/materials", response_model=list[CourseMaterialRead])
async def list_materials(
    course: Annotated[Course, Depends(require_course_access)],
) -> list[CourseMaterialRead]:
    _ = course
    return []


@router.post(
    "/courses/{course_id}/materials",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_material(
    course: Annotated[Course, Depends(require_course_manage_permission)],
    current_user: Annotated[User, Depends(get_current_user)],
    title: str = Form(...),
    uploaded_by: Optional[str] = Form(None),
    file: UploadFile = File(...),
) -> CourseMaterialRead:
    _ = uploaded_by
    now = datetime.now(timezone.utc)
    return CourseMaterialRead(
        id=str(uuid4()),
        course_id=course.id,
        uploaded_by=current_user.id,
        title=title,
        file_name=file.filename or "uploaded-material",
        file_type=file.content_type or "application/octet-stream",
        storage_uri=f"local://uploads/{course.id}/{file.filename or 'uploaded-material'}",
        status="uploaded",
        checksum=None,
        created_at=now,
        updated_at=now,
    )
