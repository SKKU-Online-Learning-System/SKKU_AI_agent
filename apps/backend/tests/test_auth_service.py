import importlib
import importlib.util

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import JWTService, PasswordService
from app.models import Base, User, UserRole


def load_auth_module():
    assert importlib.util.find_spec("app.services.auth_service") is not None
    return importlib.import_module("app.services.auth_service")


def build_service(auth_module):
    return auth_module.AuthService(
        auth_module.LocalPasswordAuthProvider(PasswordService()),
        JWTService("test-secret", "HS256", 3600),
    )


def add_local_user(session: Session) -> User:
    user = User(
        name="Student",
        email="student@skku.edu",
        password_hash=PasswordHasher().hash("password123"),
        role=UserRole.student,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_auth_service_normalizes_email_and_returns_token() -> None:
    auth = load_auth_module()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = add_local_user(session)
        service = build_service(auth)

        result = service.login(session, " STUDENT@SKKU.EDU ", "password123")

        assert result.user.id == user.id
        assert JWTService("test-secret", "HS256", 3600).decode_access_token(
            result.access_token
        ) == user.id


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("missing@skku.edu", "password123"),
        ("student@skku.edu", "wrong"),
    ],
)
def test_auth_service_uses_one_error_for_credential_failures(
    email: str,
    password: str,
) -> None:
    auth = load_auth_module()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        add_local_user(session)
        service = build_service(auth)

        with pytest.raises(auth.InvalidCredentialsError):
            service.login(session, email, password)


def test_external_only_user_cannot_use_local_password_login() -> None:
    auth = load_auth_module()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            User(
                name="SSO Student",
                email="sso@skku.edu",
                external_auth_id="skku-sso-123",
                role=UserRole.student,
            )
        )
        session.commit()
        service = build_service(auth)

        with pytest.raises(auth.InvalidCredentialsError):
            service.login(session, "sso@skku.edu", "password123")
