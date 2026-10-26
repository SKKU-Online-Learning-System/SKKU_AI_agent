from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.security import JWTService
from app.db.seed import seed_database
from app.db.session import get_db
from app.main import app
from app.models import Base
from app.services import login_throttle


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as session:
        seed_database(session, "password123")

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_session_cookie(client: TestClient) -> None:
    """The client is shared by the module; a login must not authenticate the next test."""
    client.cookies.clear()


@pytest.mark.parametrize(
    ("email", "role"),
    [
        ("admin@skku.edu", "admin"),
        ("professor@skku.edu", "professor"),
        ("student@skku.edu", "student"),
    ],
)
def test_seed_accounts_can_login(client: TestClient, email: str, role: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password123"},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"access_token", "token_type", "user"}
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert body["user"]["role"] == role
    assert set(body["user"]) == {"id", "name", "email", "role"}


def test_access_token_resolves_current_user(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login",
        json={"email": "student@skku.edu", "password": "password123"},
    ).json()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json() == login["user"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("missing@skku.edu", "password123"),
        ("student@skku.edu", "wrong"),
    ],
)
def test_login_uses_identical_unauthorized_response_for_bad_credentials(
    client: TestClient,
    email: str,
    password: str,
) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer malformed-token"},
        {"Authorization": "Basic credentials"},
    ],
)
def test_me_rejects_missing_or_malformed_bearer_token(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    response = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired access token"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_rejects_expired_wrong_type_and_unknown_user_tokens(client: TestClient) -> None:
    settings = get_settings()
    token_service = JWTService(
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expires_in,
    )
    now = datetime.now(timezone.utc)
    expired = token_service.create_access_token(
        "user-123",
        now=now - timedelta(seconds=settings.jwt_expires_in + 1),
    )
    wrong_type = jwt.encode(
        {
            "sub": "user-123",
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    unknown_user = token_service.create_access_token("missing-user", now=now)

    for token in (expired, wrong_type, unknown_user):
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or expired access token"}


def test_login_records_a_login_event(client: TestClient) -> None:
    from app.models import LoginEvent

    def events() -> list[LoginEvent]:
        session = next(app.dependency_overrides[get_db]())
        return session.query(LoginEvent).order_by(LoginEvent.created_at).all()

    before = len(events())
    admin = client.post(
        "/api/auth/login", json={"email": "admin@skku.edu", "password": "password123"}
    )
    student = client.post(
        "/api/auth/login", json={"email": "student@skku.edu", "password": "password123"}
    )

    assert admin.status_code == 200 and student.status_code == 200
    after = events()
    # Staff never use the agent, so only the student's login is a usage event.
    assert len(after) == before + 1
    assert after[-1].user_id == student.json()["user"]["id"]


def test_login_sets_an_httponly_cookie_that_authenticates(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login", json={"email": "student@skku.edu", "password": "password123"}
    )
    cookie = login.headers["set-cookie"]
    assert "skku_access_token=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    assert client.get("/api/auth/me").json()["email"] == "student@skku.edu"

    client.post("/api/auth/logout", headers={"X-Requested-With": "XMLHttpRequest"})
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_authenticated_unsafe_request_needs_the_csrf_header(client: TestClient) -> None:
    client.post("/api/auth/login", json={"email": "student@skku.edu", "password": "password123"})
    blocked = client.post("/api/chat", json={})
    allowed = client.post("/api/chat", json={}, headers={"X-Requested-With": "XMLHttpRequest"})

    assert blocked.status_code == 403
    assert blocked.json() == {"detail": "Missing CSRF header"}
    # Past authentication; the empty body is what fails now.
    assert allowed.status_code == 422


def test_repeated_failed_logins_are_throttled_per_account(client: TestClient) -> None:
    def attempt(password: str):
        return client.post(
            "/api/auth/login", json={"email": "Professor@skku.edu", "password": password}
        )

    for _ in range(5):
        assert attempt("wrong").status_code == 401

    blocked = attempt("password123")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    # Another account is not affected.
    assert (
        client.post(
            "/api/auth/login", json={"email": "admin@skku.edu", "password": "password123"}
        ).status_code
        == 200
    )


def test_throttle_is_per_address_ignores_unknown_accounts_and_stays_bounded(
    client: TestClient, monkeypatch
) -> None:
    for _ in range(5):
        login_throttle.record_failure("professor@skku.edu", "10.0.0.1")
    assert login_throttle.retry_after("professor@skku.edu", "10.0.0.1") > 0
    assert login_throttle.retry_after("professor@skku.edu", "10.0.0.2") == 0

    for _ in range(10):
        client.post("/api/auth/login", json={"email": "nobody@skku.edu", "password": "x"})
    assert login_throttle.retry_after("nobody@skku.edu", "testclient") == 0

    monkeypatch.setattr(login_throttle, "MAX_TRACKED", 3)
    login_throttle.reset()
    for index in range(10):
        login_throttle.record_failure(f"user{index}@skku.edu", "10.0.0.1")
    assert len(login_throttle._failures) == 3
