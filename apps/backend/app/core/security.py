from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jose import JWTError, jwt


class InvalidAccessTokenError(Exception):
    """Raised when an access token cannot be trusted or used."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    token_id: str
    expires_at: int


class PasswordService:
    def __init__(self, hasher: Optional[PasswordHasher] = None) -> None:
        self.hasher = hasher or PasswordHasher()

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self.hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False


class JWTService:
    def __init__(self, secret: str, algorithm: str, expires_in: int) -> None:
        if expires_in <= 0:
            raise ValueError("JWT expiration must be positive.")

        self.secret = secret
        self.algorithm = algorithm
        self.expires_in = expires_in

    def create_access_token(self, user_id: str, now: Optional[datetime] = None) -> str:
        issued_at = now or datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "jti": str(uuid4()),
            "type": "access",
            "iat": int(issued_at.timestamp()),
            "exp": int((issued_at + timedelta(seconds=self.expires_in)).timestamp()),
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def decode_access_token(self, token: str, now: Optional[datetime] = None) -> str:
        return self.decode_access_claims(token, now).user_id

    def decode_access_claims(
        self, token: str, now: Optional[datetime] = None
    ) -> AccessClaims:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                options={"verify_exp": False},
            )
        except JWTError as exc:
            raise InvalidAccessTokenError from exc

        current_time = int((now or datetime.now(timezone.utc)).timestamp())
        expires_at = payload.get("exp")
        subject = payload.get("sub")
        token_id = payload.get("jti")

        if type(expires_at) is not int or expires_at <= current_time:
            raise InvalidAccessTokenError
        if payload.get("type") != "access":
            raise InvalidAccessTokenError
        if not isinstance(subject, str) or not subject:
            raise InvalidAccessTokenError

        if not isinstance(token_id, str) or len(token_id) != 36:
            raise InvalidAccessTokenError("Token has no revocable identifier")
        return AccessClaims(user_id=subject, token_id=token_id, expires_at=expires_at)
