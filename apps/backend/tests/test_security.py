import importlib
import importlib.util
from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher
from jose import jwt
from pydantic import ValidationError

from app.core.config import Settings


def load_security_module():
    assert importlib.util.find_spec("app.core.security") is not None
    return importlib.import_module("app.core.security")


def test_auth_settings_have_secure_token_configuration() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_env == "local"
    assert settings.jwt_secret == "local-dev-change-me"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expires_in == 3600


def test_local_settings_allow_documented_development_jwt_placeholder() -> None:
    settings = Settings(
        app_env="local",
        jwt_secret="replace-with-a-long-random-secret",
        _env_file=None,
    )

    assert settings.jwt_secret == "replace-with-a-long-random-secret"


@pytest.mark.parametrize(
    "jwt_secret",
    [
        "local-dev-change-me",
        "replace-with-a-long-random-secret",
        "short-production-secret",
    ],
)
def test_nonlocal_settings_reject_insecure_jwt_secrets(jwt_secret: str) -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(app_env="production", jwt_secret=jwt_secret, _env_file=None)


def test_nonlocal_settings_accept_unique_jwt_secret_of_at_least_32_characters() -> None:
    settings = Settings(
        app_env="production",
        jwt_secret="u9N4qT2mX7vL5cR8pK3sD6hJ1wF0aBzY",
        _env_file=None,
    )

    assert settings.jwt_secret == "u9N4qT2mX7vL5cR8pK3sD6hJ1wF0aBzY"


def test_password_service_verifies_argon2_hash_without_leaking_hash_errors() -> None:
    security = load_security_module()
    password_hash = PasswordHasher().hash("password123")
    service = security.PasswordService()

    assert service.verify("password123", password_hash) is True
    assert service.verify("wrong", password_hash) is False
    assert service.verify("password123", "not-an-argon2-hash") is False


def test_jwt_service_round_trips_access_token_subject() -> None:
    security = load_security_module()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    service = security.JWTService("test-secret", "HS256", 3600)

    token = service.create_access_token("user-123", now=now)
    claims = jwt.get_unverified_claims(token)

    assert claims == {
        "sub": "user-123",
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=3600)).timestamp()),
    }
    assert service.decode_access_token(token, now=now + timedelta(minutes=1)) == "user-123"


def test_jwt_service_rejects_expired_token() -> None:
    security = load_security_module()
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    service = security.JWTService("test-secret", "HS256", 1)
    token = service.create_access_token("user-123", now=now)

    with pytest.raises(security.InvalidAccessTokenError):
        service.decode_access_token(token, now=now + timedelta(seconds=2))


def test_jwt_service_rejects_wrong_signature_and_wrong_type() -> None:
    security = load_security_module()
    now = datetime.now(timezone.utc)
    service = security.JWTService("test-secret", "HS256", 3600)
    wrong_signature = security.JWTService("other-secret", "HS256", 3600).create_access_token(
        "user-123",
        now=now,
    )
    wrong_type = jwt.encode(
        {
            "sub": "user-123",
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        "test-secret",
        algorithm="HS256",
    )

    with pytest.raises(security.InvalidAccessTokenError):
        service.decode_access_token(wrong_signature, now=now)
    with pytest.raises(security.InvalidAccessTokenError):
        service.decode_access_token(wrong_type, now=now)
