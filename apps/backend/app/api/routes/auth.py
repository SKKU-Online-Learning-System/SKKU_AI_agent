from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    ACCESS_TOKEN_COOKIE,
    bearer_headers,
    get_auth_service,
    get_current_user,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import LoginEvent, User, UserRole
from app.schemas import AuthUserRead, LoginRequest, LoginResponse
from app.services import login_throttle
from app.services.auth_service import AuthService, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    address = request.client.host if request.client else "unknown"
    wait = login_throttle.retry_after(payload.email, address)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(wait)},
        )
    try:
        result = auth_service.login(session, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        # Only an account that exists has a password to guess; counting made-up
        # addresses would only let a script fill the table.
        if session.scalar(
            select(User.id).where(func.lower(User.email) == payload.email.strip().lower())
        ):
            login_throttle.record_failure(payload.email, address)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers=bearer_headers,
        ) from exc

    login_throttle.record_success(payload.email, address)
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
        access_token=result.access_token,
        user=AuthUserRead.model_validate(result.user),
    )


@router.get("/me", response_model=AuthUserRead)
def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    response.delete_cookie(
        ACCESS_TOKEN_COOKIE,
        httponly=True,
        secure=settings.app_env != "local",
        samesite="lax",
    )
