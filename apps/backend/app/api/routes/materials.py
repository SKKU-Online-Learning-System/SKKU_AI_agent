from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile, status

from app.schemas import CourseMaterialRead

router = APIRouter(tags=["materials"])


@router.get("/courses/{course_id}/materials", response_model=list[CourseMaterialRead])
async def list_materials(course_id: str) -> list[CourseMaterialRead]:
    _ = course_id
    return []


@router.post(
    "/courses/{course_id}/materials",
    response_model=CourseMaterialRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_material(
    course_id: str,
    title: str = Form(...),
    uploaded_by: str = Form(...),
    file: UploadFile = File(...),
) -> CourseMaterialRead:
    now = datetime.now(timezone.utc)
    return CourseMaterialRead(
        id=str(uuid4()),
        course_id=course_id,
        uploaded_by=uploaded_by,
        title=title,
        file_name=file.filename or "uploaded-material",
        file_type=file.content_type or "application/octet-stream",
        storage_uri=f"local://uploads/{course_id}/{file.filename or 'uploaded-material'}",
        status="uploaded",
        checksum=None,
        created_at=now,
        updated_at=now,
    )
