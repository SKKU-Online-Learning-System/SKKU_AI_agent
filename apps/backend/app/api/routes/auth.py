from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    ACCESS_TOKEN_COOKIE,
    CSRF_HEADER,
    bearer_headers,
    get_auth_service,
    get_current_user,
    get_jwt_service,
    request_access_token,
)
from app.core.config import Settings, get_settings
from app.core.security import InvalidAccessTokenError, JWTService
from app.db.session import get_db
from app.models import LoginEvent, User, UserRole
from app.schemas import AuthUserRead, LoginRequest, LoginResponse
from app.services import login_throttle
from app.services.access_session import revoke_access_token
from app.services.auth_service import AuthService, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


def _check_browser_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed")


@router.post("/login", response_model=LoginResponse, response_model_exclude_none=True)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    _check_browser_origin(request, settings)
    address = request.client.host if request.client else "unknown"
    wait = login_throttle.claim_attempt(payload.email, address)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )
    try:
        result = auth_service.login(session, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers=bearer_headers,
        ) from exc

    login_throttle.record_success(payload.email, address)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        result.access_token,
        max_age=settings.jwt_expires_in,
        httponly=True,
        secure=settings.app_env != "local",
        samesite="lax",
    )
    # Only learners use the agent, so only their logins are usage worth charting.
    if result.user.role == UserRole.student:
        session.add(LoginEvent(user_id=result.user.id))
        session.commit()
    return LoginResponse(
        access_token=(
            None if request.headers.get("origin") or request.headers.get(CSRF_HEADER)
            else result.access_token
        ),
        user=AuthUserRead.model_validate(result.user),
    )


@router.get("/me", response_model=AuthUserRead)
def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_db)],
    jwt_service: Annotated[JWTService, Depends(get_jwt_service)],
    token: Annotated[str | None, Depends(request_access_token)],
) -> None:
    _check_browser_origin(request, settings)
    if token:
        try:
            claims = jwt_service.decode_access_claims(token)
        except InvalidAccessTokenError:
            pass
        else:
            revoke_access_token(session, claims)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        ACCESS_TOKEN_COOKIE,
        httponly=True,
        secure=settings.app_env != "local",
        samesite="lax",
    )
