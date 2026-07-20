from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_course_access, require_role
from app.db.session import get_db
from app.models import Course, User, UserRole
from app.schemas import CourseCreate, CourseRead
from app.services.rbac_service import list_accessible_courses

router = APIRouter(prefix="/courses", tags=["courses"])


def course_to_read(
    course: Course,
    code: Optional[str] = None,
    instructor_name: Optional[str] = None,
) -> CourseRead:
    return CourseRead(
        id=course.id,
        code=code or course.id,
        title=course.name,
        term=course.semester,
        instructor_id=course.professor_id,
        instructor_name=instructor_name or course.professor.name,
        agent_status="active" if course.is_active else "disabled",
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.get("", response_model=list[CourseRead])
def list_courses(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[CourseRead]:
    return [course_to_read(course) for course in list_accessible_courses(session, current_user)]


@router.post("", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    session: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_role(UserRole.admin))],
) -> CourseRead:
    professor = session.get(User, payload.instructor_id)
    if professor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Professor not found",
        )
    if professor.role != UserRole.professor:
        raise HTTPException(
            status_code=422,
            detail="Instructor must have professor role",
        )

    course = Course(
        name=payload.title,
        semester=payload.term,
        description=None,
        professor_id=professor.id,
        is_active=payload.agent_status == "active",
    )
    session.add(course)
    session.commit()
    session.refresh(course)

    return course_to_read(course, code=payload.code, instructor_name=professor.name)


@router.get("/{course_id}", response_model=CourseRead)
def get_course(course: Annotated[Course, Depends(require_course_access)]) -> CourseRead:
    return course_to_read(course)
