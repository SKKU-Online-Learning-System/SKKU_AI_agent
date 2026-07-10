from __future__ import annotations

from typing import Annotated, NoReturn, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import InvalidAccessTokenError, JWTService, PasswordService
from app.db.session import get_db
from app.models import User
from app.services.auth_service import AuthService, LocalPasswordAuthProvider

bearer_scheme = HTTPBearer(auto_error=False)
bearer_headers = {"WWW-Authenticate": "Bearer"}


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
