from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, status

from app.schemas import CourseCreate, CourseRead

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseRead])
async def list_courses() -> list[CourseRead]:
    return []


@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
async def create_course(payload: CourseCreate) -> CourseRead:
    now = datetime.now(timezone.utc)
    return CourseRead(
        id=str(uuid4()),
        code=payload.code,
        title=payload.title,
        term=payload.term,
        instructor_id=payload.instructor_id,
        agent_status=payload.agent_status,
        created_at=now,
        updated_at=now,
    )
