from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.db.session import get_db
from app.models import Course, CourseAccess, CourseMaterial, User, UserRole
from app.schemas import (
    AdminCourseAccessRead,
    AdminCourseCreate,
    AdminCourseRead,
    AdminCourseUpdate,
    UserRead,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(UserRole.admin))],
)


@router.get("/stats")
async def get_stats(session: Annotated[Session, Depends(get_db)]) -> dict[str, int]:
    return {
        "users": session.scalar(select(func.count()).select_from(User)) or 0,
        "courses": session.scalar(select(func.count()).select_from(Course)) or 0,
        "materials": session.scalar(select(func.count()).select_from(CourseMaterial)) or 0,
        "chatSessions": 0,
        "chatLogs": 0,
    }


def get_course_or_404(session: Session, course_id: str) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
        )

    return course


def get_professor_or_404(session: Session, professor_id: str) -> User:
    professor = session.get(User, professor_id)
    if professor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Professor not found",
        )
    if professor.role != UserRole.professor:
        raise HTTPException(
            status_code=422,
            detail="Professor id must reference a professor user",
        )

    return professor


def course_access_count(session: Session, course_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(CourseAccess)
            .where(CourseAccess.course_id == course_id)
        )
        or 0
    )


def course_to_admin_read(session: Session, course: Course) -> AdminCourseRead:
    professor = session.get(User, course.professor_id)
    return AdminCourseRead(
        id=course.id,
        name=course.name,
        semester=course.semester,
        description=course.description,
        professor_id=course.professor_id,
        professor_name=professor.name if professor else "Unknown professor",
        is_active=course.is_active,
        student_access_count=course_access_count(session, course.id),
        created_at=course.created_at,
        updated_at=course.updated_at,
    )


@router.get("/users", response_model=list[UserRead])
def list_users(
    session: Annotated[Session, Depends(get_db)],
    role: Optional[UserRole] = Query(default=None),
) -> list[User]:
    statement = select(User).order_by(User.name)
    if role is not None:
        statement = statement.where(User.role == role)

    return list(session.scalars(statement).all())


@router.get("/courses", response_model=list[AdminCourseRead])
def list_courses(
    session: Annotated[Session, Depends(get_db)],
    semester: Optional[str] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    professor_id: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
) -> list[AdminCourseRead]:
    statement = select(Course).order_by(Course.created_at.desc(), Course.name)

    if semester:
        statement = statement.where(Course.semester == semester)
    if is_active is not None:
        statement = statement.where(Course.is_active.is_(is_active))
    if professor_id:
        statement = statement.where(Course.professor_id == professor_id)
    if keyword:
        pattern = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                Course.name.ilike(pattern),
                Course.semester.ilike(pattern),
                Course.description.ilike(pattern),
            )
        )

    courses = session.scalars(statement).all()
    return [course_to_admin_read(session, course) for course in courses]


@router.post(
    "/courses",
    response_model=AdminCourseRead,
    status_code=status.HTTP_201_CREATED,
)
def create_course(
    payload: AdminCourseCreate,
    session: Annotated[Session, Depends(get_db)],
) -> AdminCourseRead:
    professor = get_professor_or_404(session, payload.professor_id)
    course = Course(
        name=payload.name,
        semester=payload.semester,
        description=payload.description,
        professor_id=professor.id,
        is_active=payload.is_active,
    )
    session.add(course)
    session.commit()
    session.refresh(course)

    return course_to_admin_read(session, course)


@router.get("/courses/{course_id}", response_model=AdminCourseRead)
def get_course(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> AdminCourseRead:
    return course_to_admin_read(session, get_course_or_404(session, course_id))


@router.patch("/courses/{course_id}", response_model=AdminCourseRead)
def update_course(
    course_id: str,
    payload: AdminCourseUpdate,
    session: Annotated[Session, Depends(get_db)],
) -> AdminCourseRead:
    course = get_course_or_404(session, course_id)

    if "professor_id" in payload.model_fields_set:
        if payload.professor_id is None:
            raise HTTPException(
                status_code=422,
                detail="Professor id is required",
            )
        professor = get_professor_or_404(session, payload.professor_id)
        course.professor_id = professor.id
    if "name" in payload.model_fields_set and payload.name is not None:
        course.name = payload.name
    if "semester" in payload.model_fields_set and payload.semester is not None:
        course.semester = payload.semester
    if "description" in payload.model_fields_set:
        course.description = payload.description
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        course.is_active = payload.is_active

    session.commit()
    session.refresh(course)
    return course_to_admin_read(session, course)


@router.patch("/courses/{course_id}/deactivate", response_model=AdminCourseRead)
def deactivate_course(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> AdminCourseRead:
    course = get_course_or_404(session, course_id)
    course.is_active = False
    session.commit()
    session.refresh(course)
    return course_to_admin_read(session, course)


@router.patch("/courses/{course_id}/activate", response_model=AdminCourseRead)
def activate_course(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> AdminCourseRead:
    course = get_course_or_404(session, course_id)
    course.is_active = True
    session.commit()
    session.refresh(course)
    return course_to_admin_read(session, course)


@router.get("/courses/{course_id}/access", response_model=list[AdminCourseAccessRead])
def list_course_access(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
) -> list[AdminCourseAccessRead]:
    get_course_or_404(session, course_id)
    rows = session.execute(
        select(CourseAccess, User)
        .join(User, User.id == CourseAccess.user_id)
        .where(CourseAccess.course_id == course_id)
        .order_by(User.name)
    ).all()

    return [
        AdminCourseAccessRead(
            id=access.id,
            course_id=access.course_id,
            user_id=user.id,
            user_name=user.name,
            user_email=user.email,
            access_role=access.access_role,
            created_at=access.created_at,
        )
        for access, user in rows
    ]
