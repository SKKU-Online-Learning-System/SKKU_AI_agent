from time import time

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import AccessClaims, InvalidAccessTokenError, JWTService
from app.models import RevokedAccessToken, User


def resolve_access_user(
    session: Session, jwt_service: JWTService, token: str
) -> tuple[User, AccessClaims]:
    claims = jwt_service.decode_access_claims(token)
    if session.get(RevokedAccessToken, claims.token_id) is not None:
        raise InvalidAccessTokenError("Token has been revoked")
    user = session.get(User, claims.user_id)
    if user is None:
        raise InvalidAccessTokenError("Unknown user")
    return user, claims


def revoke_access_token(session: Session, claims: AccessClaims) -> None:
    session.execute(
        delete(RevokedAccessToken).where(RevokedAccessToken.expires_at <= int(time()))
    )
    if session.get(RevokedAccessToken, claims.token_id) is None:
        session.add(RevokedAccessToken(token_id=claims.token_id, expires_at=claims.expires_at))
    try:
        session.commit()
    except IntegrityError:
        # A simultaneous logout may have already revoked this exact token.
        session.rollback()
        if session.get(RevokedAccessToken, claims.token_id) is None:
            raise
