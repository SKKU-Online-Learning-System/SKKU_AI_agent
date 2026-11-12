from __future__ import annotations

from typing import Annotated, NoReturn, Optional, Sequence, Union

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import InvalidAccessTokenError, JWTService, PasswordService
from app.db.session import get_db
from app.models import Course, User, UserRole
from app.services.access_session import resolve_access_user
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

# The browser keeps the access token in an httpOnly cookie, out of reach of page
# scripts. Bearer headers still work for API clients and tests.
ACCESS_TOKEN_COOKIE = "skku_access_token"
# A cookie rides along on any same-site request, so an unsafe request
# authenticated by it must also carry this header: a cross-origin page cannot
# add a custom header without a CORS preflight, which only our origins pass.
CSRF_HEADER = "X-Requested-With"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
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


def request_access_token(
    request: Request,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(bearer_scheme),
    ],
) -> str | None:
    if credentials is not None:
        return credentials.credentials
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token and request.method not in SAFE_METHODS and not request.headers.get(CSRF_HEADER):
        raise_forbidden("Missing CSRF header")
    return token


def get_current_user(
    response: Response,
    token: Annotated[str | None, Depends(request_access_token)],
    session: Annotated[Session, Depends(get_db)],
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
) -> User:
    if not token:
        raise_invalid_access_token()
    try:
        user, _ = resolve_access_user(session, jwt_service, token)
    except InvalidAccessTokenError:
        raise_invalid_access_token()
    response.headers["Cache-Control"] = "private, no-store"
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
