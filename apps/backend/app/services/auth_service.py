from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import JWTService, PasswordService
from app.models import User


class InvalidCredentialsError(Exception):
    """Raised without revealing which credential failed."""


class AuthenticationProvider(Protocol):
    def authenticate(
        self,
        session: Session,
        email: str,
        password: str,
    ) -> Optional[User]:
        raise NotImplementedError


@dataclass(frozen=True)
class AuthResult:
    user: User
    access_token: str


class LocalPasswordAuthProvider:
    def __init__(self, password_service: PasswordService) -> None:
        self.password_service = password_service

    def authenticate(
        self,
        session: Session,
        email: str,
        password: str,
    ) -> Optional[User]:
        normalized_email = email.strip().lower()
        user = session.scalar(select(User).where(func.lower(User.email) == normalized_email))

        if user is None or user.password_hash is None:
            return None
        if not self.password_service.verify(password, user.password_hash):
            return None

        return user


class AuthService:
    def __init__(
        self,
        provider: AuthenticationProvider,
        jwt_service: JWTService,
    ) -> None:
        self.provider = provider
        self.jwt_service = jwt_service

    def login(self, session: Session, email: str, password: str) -> AuthResult:
        user = self.provider.authenticate(session, email, password)
        if user is None:
            raise InvalidCredentialsError

        return AuthResult(
            user=user,
            access_token=self.jwt_service.create_access_token(user.id),
        )
