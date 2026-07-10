# Backend Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Seed-compatible email/password login, JWT access-token issuance, and authenticated current-user lookup to the FastAPI backend.

**Architecture:** Keep password and JWT primitives in `app.core.security`, credential-provider abstraction and local authentication in `app.services.auth_service`, and HTTP Bearer resolution in `app.api.deps`. The auth router only maps HTTP requests and responses, allowing a future SSO provider to replace local credential verification without rewriting protected routes.

**Tech Stack:** Python 3.9+, FastAPI, SQLAlchemy 2.x, argon2-cffi, python-jose, Pydantic 2, pytest, Ruff, mypy.

## Global Constraints

- Endpoints are `POST /api/auth/login` and `GET /api/auth/me`.
- Do not add a logout endpoint; the client deletes its stateless access token.
- Login failures never distinguish unknown email, external-only account, or wrong password.
- JWT claims are `sub`, `type=access`, `iat`, and `exp`.
- JWT decoding accepts only the configured algorithm.
- `JWT_EXPIRES_IN` is expressed in seconds and defaults to `3600`.
- Preserve existing FastAPI router composition and synchronous SQLAlchemy sessions.
- Frontend login UI, refresh tokens, SSO callbacks, and password reset are out of scope.

---

### Task 1: Password and JWT Security Primitives

**Files:**
- Modify: `apps/backend/app/core/config.py`
- Create: `apps/backend/app/core/security.py`
- Create: `apps/backend/tests/test_security.py`

**Interfaces:**
- Produces: `PasswordService.verify(password: str, password_hash: str) -> bool`.
- Produces: `JWTService.create_access_token(user_id: str, now: datetime | None = None) -> str`.
- Produces: `JWTService.decode_access_token(token: str) -> str` returning the subject user ID.
- Produces: `InvalidAccessTokenError` for all token failures.

- [ ] **Step 1: Write failing security tests**

Create tests using a real Argon2 hash and deterministic UTC timestamps:

```python
from datetime import datetime, timedelta, timezone

import pytest
from argon2 import PasswordHasher

from app.core.security import InvalidAccessTokenError, JWTService, PasswordService


def test_password_service_verifies_argon2_hash_without_leaking_hash_errors() -> None:
    password_hash = PasswordHasher().hash("password123")
    service = PasswordService()

    assert service.verify("password123", password_hash) is True
    assert service.verify("wrong", password_hash) is False
    assert service.verify("password123", "not-an-argon2-hash") is False


def test_jwt_service_round_trips_access_token_subject() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    service = JWTService(secret="test-secret", algorithm="HS256", expires_in=3600)

    token = service.create_access_token("user-123", now=now)

    assert service.decode_access_token(token, now=now + timedelta(minutes=1)) == "user-123"


def test_jwt_service_rejects_expired_and_wrong_type_tokens() -> None:
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    service = JWTService(secret="test-secret", algorithm="HS256", expires_in=1)
    token = service.create_access_token("user-123", now=now)

    with pytest.raises(InvalidAccessTokenError):
        service.decode_access_token(token, now=now + timedelta(seconds=2))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
cd apps/backend
python -m pytest tests/test_security.py -q -p no:cacheprovider
```

Expected: failure because `app.core.security` does not exist.

- [ ] **Step 3: Add JWT settings and minimal security implementation**

Add these settings:

```python
jwt_algorithm: str = "HS256"
jwt_expires_in: int = Field(default=3600, gt=0)
```

Implement `PasswordService` with `argon2.PasswordHasher.verify`, catching
`InvalidHashError` and `VerificationError`. Implement `JWTService` with `python-jose`, including
the exact claims from the design. Its constructor accepts explicit secret, algorithm, and
expiration values so tests and future provider wiring do not depend on global state.

For deterministic expiry tests, `decode_access_token` accepts an optional `now`; validate `exp`
against that time after decoding with signature and algorithm checks.

- [ ] **Step 4: Run security tests and static checks**

```powershell
python -m pytest tests/test_security.py -q -p no:cacheprovider
python -m ruff check app/core tests/test_security.py
python -m mypy app/core
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit security primitives**

```powershell
git add apps/backend/app/core apps/backend/tests/test_security.py
git commit -m "Add authentication security primitives"
```

---

### Task 2: Replaceable Authentication Provider and Service

**Files:**
- Create: `apps/backend/app/services/auth_service.py`
- Create: `apps/backend/tests/test_auth_service.py`

**Interfaces:**
- Produces: `AuthenticationProvider` protocol.
- Produces: `LocalPasswordAuthProvider.authenticate(session, email, password) -> User | None`.
- Produces: `AuthService.login(session, email, password) -> AuthResult`.
- Produces: `InvalidCredentialsError` for every credential failure.
- Consumes: `PasswordService`, `JWTService`, SQLAlchemy `Session`, and `User`.

- [ ] **Step 1: Write failing provider/service tests**

Use an in-memory SQLite database and real Argon2 hashes:

```python
from argon2 import PasswordHasher
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import JWTService, PasswordService
from app.models import Base, User, UserRole
from app.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    LocalPasswordAuthProvider,
)


def test_auth_service_normalizes_email_and_returns_token() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(
            name="Student",
            email="student@skku.edu",
            password_hash=PasswordHasher().hash("password123"),
            role=UserRole.student,
        )
        session.add(user)
        session.commit()

        service = AuthService(
            LocalPasswordAuthProvider(PasswordService()),
            JWTService("test-secret", "HS256", 3600),
        )
        result = service.login(session, " STUDENT@SKKU.EDU ", "password123")

        assert result.user.id == user.id
        assert result.access_token


@pytest.mark.parametrize("email,password", [
    ("missing@skku.edu", "password123"),
    ("student@skku.edu", "wrong"),
])
def test_auth_service_uses_one_error_for_all_credential_failures(email: str, password: str) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(
            name="Student",
            email="student@skku.edu",
            password_hash=PasswordHasher().hash("password123"),
            role=UserRole.student,
        ))
        session.commit()
        service = AuthService(
            LocalPasswordAuthProvider(PasswordService()),
            JWTService("test-secret", "HS256", 3600),
        )

        with pytest.raises(InvalidCredentialsError):
            service.login(session, email, password)
```

Add a separate external-only user with `external_auth_id="sso-user"` and no password hash, then
assert `InvalidCredentialsError` when local login is attempted for that email.

- [ ] **Step 2: Run service tests and verify RED**

```powershell
python -m pytest tests/test_auth_service.py -q -p no:cacheprovider
```

Expected: failure because `app.services.auth_service` does not exist.

- [ ] **Step 3: Implement the provider protocol and local service**

Define:

```python
class AuthenticationProvider(Protocol):
    def authenticate(self, session: Session, email: str, password: str) -> Optional[User]:
        raise NotImplementedError


@dataclass(frozen=True)
class AuthResult:
    user: User
    access_token: str
```

`LocalPasswordAuthProvider` normalizes email and queries with `func.lower(User.email)`. It returns
`None` when the user is absent, has no password hash, or password verification fails.
`AuthService.login` raises `InvalidCredentialsError` for `None`; otherwise it issues a JWT for
the persisted user ID.

- [ ] **Step 4: Run service tests and static checks**

```powershell
python -m pytest tests/test_auth_service.py -q -p no:cacheprovider
python -m ruff check app/services/auth_service.py tests/test_auth_service.py
python -m mypy app/services/auth_service.py
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit the authentication service**

```powershell
git add apps/backend/app/services/auth_service.py apps/backend/tests/test_auth_service.py
git commit -m "Add replaceable authentication service"
```

---

### Task 3: Login and Current-User API

**Files:**
- Create: `apps/backend/app/schemas/auth.py`
- Modify: `apps/backend/app/schemas/__init__.py`
- Create: `apps/backend/app/api/deps.py`
- Create: `apps/backend/app/api/routes/auth.py`
- Modify: `apps/backend/app/main.py`
- Create: `apps/backend/tests/test_auth_api.py`

**Interfaces:**
- Produces: `POST /api/auth/login` with `LoginRequest -> LoginResponse`.
- Produces: `GET /api/auth/me -> AuthUserRead`.
- Produces: `get_current_user(credentials, session, jwt_service) -> User` for protected routes.
- Consumes: `get_db`, `AuthService`, `JWTService`, and configured JWT settings.

- [ ] **Step 1: Write failing API tests**

Create a FastAPI test fixture using `StaticPool`, override `get_db`, create the real schema, and
call `seed_database`. Test:

```python
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
    assert response.json()["token_type"] == "bearer"
    assert response.json()["user"]["role"] == role
    assert response.json()["access_token"]


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
    assert response.json()["email"] == "student@skku.edu"
```

Add tests asserting identical 401 bodies and Bearer headers for unknown email and wrong password,
plus 401 for missing/malformed token. Use `JWTService` to create expired, wrong-type, and unknown
user tokens and assert `/me` returns the single token error.

- [ ] **Step 2: Run API tests and verify RED**

```powershell
python -m pytest tests/test_auth_api.py -q -p no:cacheprovider
```

Expected: 404 failures because the auth router is not registered.

- [ ] **Step 3: Add auth DTOs, dependencies, and router**

Define plain Pydantic models so token fields remain snake_case:

```python
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AuthUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: EmailStr
    role: Literal["student", "professor", "admin"]


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: AuthUserRead
```

Use `HTTPBearer(auto_error=False)`. `get_current_user` must validate the token, load the subject
from the database, and return one HTTP 401 response with `WWW-Authenticate: Bearer` for every
failure. Add factories for the configured `JWTService` and default local `AuthService`.

Register `auth.router` in `main.py` with the existing `/api` prefix.

- [ ] **Step 4: Run API and complete backend tests**

```powershell
python -m pytest tests/test_auth_api.py -q -p no:cacheprovider
python -m pytest tests -q -p no:cacheprovider
python -m ruff check app tests
python -m mypy app
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit the HTTP API**

```powershell
git add apps/backend/app/api apps/backend/app/schemas apps/backend/app/main.py apps/backend/tests/test_auth_api.py
git commit -m "Add JWT authentication API"
```

---

### Task 4: Environment and API Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Produces: documented JWT environment and reproducible curl/PowerShell examples.
- Consumes: `/api/auth/login` and `/api/auth/me`.

- [ ] **Step 1: Add explicit JWT environment variables**

Under the existing Auth section, document:

```dotenv
JWT_SECRET=replace-with-a-long-random-secret
JWT_ALGORITHM=HS256
JWT_EXPIRES_IN=3600
```

- [ ] **Step 2: Document API and manual verification**

Add auth endpoints to the README API list and show:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"student@skku.edu","password":"password123"}'

curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```

State that logout is client-side token deletion.

- [ ] **Step 3: Run full repository verification**

```powershell
cd apps/backend
python -m pytest tests -q -p no:cacheprovider
python -m ruff check app alembic tests
python -m mypy app
cd ../..
npm.cmd run typecheck
npm.cmd run lint
git diff --check
git status --short
```

Expected: all checks exit 0; status includes only intentional auth changes and pre-existing
user-owned untracked files.

- [ ] **Step 4: Commit documentation**

```powershell
git add .env.example README.md
git commit -m "Document authentication API"
```

---

### Task 5: PostgreSQL Seed Authentication Verification

**Files:**
- Verify only; any defect must first receive a failing automated test.

**Interfaces:**
- Consumes: migrated PostgreSQL, idempotent Seed, and auth router.
- Produces: evidence that the three real Seed accounts can authenticate against PostgreSQL.

- [ ] **Step 1: Start an isolated PostgreSQL verification container**

Use a dedicated host port such as `55433` to avoid the machine's existing PostgreSQL service.
Apply Alembic and run the Seed against its `DATABASE_URL`.

- [ ] **Step 2: Start FastAPI against the verification database**

Start Uvicorn on port `8001` with the verification `DATABASE_URL`, `JWT_SECRET`,
`JWT_ALGORITHM=HS256`, and `JWT_EXPIRES_IN=3600`.

- [ ] **Step 3: Verify login and current-user flow over HTTP**

For each Seed email, call `/api/auth/login`, assert HTTP 200 and the expected role, then call
`/api/auth/me` with the returned token and assert the same user ID and email.

Also assert HTTP 401 for wrong password, unknown email, and a malformed Bearer token. Confirm the
two credential failures return identical JSON bodies.

- [ ] **Step 4: Stop verification services and run final checks**

Stop only the dedicated Uvicorn process and PostgreSQL verification container. Re-run backend
pytest, Ruff, mypy, frontend typecheck/lint, `git diff --check`, and `git status --short` before
making completion claims.
