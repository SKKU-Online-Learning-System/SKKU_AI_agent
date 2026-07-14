from __future__ import annotations

from typing import Annotated, NoReturn, Optional, Sequence, Union

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import InvalidAccessTokenError, JWTService, PasswordService
from app.db.session import get_db
from app.models import Course, User, UserRole
from app.services.auth_service import AuthService, LocalPasswordAuthProvider
from app.services.rbac_service import (
    CourseNotFoundError,
    PermissionDeniedError,
    ensure_course_access,
    ensure_course_manage_permission,
    ensure_role,
)

bearer_scheme = HTTPBearer(auto_error=False)
bearer_headers = {"WWW-Authenticate": "Bearer"}
RoleDependencyInput = Union[UserRole, str, Sequence[Union[UserRole, str]]]


def get_jwt_service(settings: Annotated[Settings, Depends(get_settings)]) -> JWTService:
    return JWTService(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_in=settings.jwt_expires_in,
    )


def get_auth_service(
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> AuthService:
    return AuthService(
        provider=LocalPasswordAuthProvider(PasswordService()),
        jwt_service=jwt_service,
    )


def raise_invalid_access_token() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired access token",
        headers=bearer_headers,
    )


def get_current_user(
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(bearer_scheme),
    ],
    session: Annotated[Session, Depends(get_db)],
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> User:
    if credentials is None:
        raise_invalid_access_token()

    try:
        user_id = jwt_service.decode_access_token(credentials.credentials)
    except InvalidAccessTokenError:
        raise_invalid_access_token()

    user = session.get(User, user_id)
    if user is None:
        raise_invalid_access_token()

    return user


def raise_forbidden(detail: str = "Forbidden") -> NoReturn:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def raise_course_not_found() -> NoReturn:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")


def require_role(roles: RoleDependencyInput):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        try:
            return ensure_role(current_user, roles)
        except PermissionDeniedError:
            raise_forbidden()

    return dependency


def authorize_course_access(session: Session, current_user: User, course_id: str) -> Course:
    try:
        return ensure_course_access(session, current_user, course_id)
    except CourseNotFoundError:
        raise_course_not_found()
    except PermissionDeniedError:
        raise_forbidden("Course access denied")


def authorize_course_manage_permission(
    session: Session,
    current_user: User,
    course_id: str,
) -> Course:
    try:
        return ensure_course_manage_permission(session, current_user, course_id)
    except CourseNotFoundError:
        raise_course_not_found()
    except PermissionDeniedError:
        raise_forbidden("Course management permission denied")


def require_course_access(
    course_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> Course:
    return authorize_course_access(session, current_user, course_id)


def require_course_manage_permission(
    course_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> Course:
    return authorize_course_manage_permission(session, current_user, course_id)
