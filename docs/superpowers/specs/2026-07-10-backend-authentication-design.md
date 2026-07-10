# Backend Authentication Design

## Goal

Add email/password login and authenticated current-user lookup to the FastAPI backend while
keeping the credential-verification boundary replaceable by a future SKKU SSO or LMS provider.

## Scope

This slice implements:

- `POST /api/auth/login`
- `GET /api/auth/me`
- Argon2 password verification against the existing `users.password_hash`
- signed JWT access-token creation and validation
- consistent authentication failures and automated API tests

There is no server-side logout endpoint because access tokens are stateless. The client logs
out by deleting its token. Refresh tokens, SSO callbacks, account linking, password reset, and
frontend login screens are outside this slice.

## Architecture

Authentication is split into four boundaries:

1. `app.schemas.auth` owns JSON request and response contracts.
2. `app.core.security` owns password verification and JWT encoding/decoding.
3. `app.services.auth_service` defines the credential-provider protocol and implements local
   password authentication.
4. `app.api.deps` converts a Bearer token into the current persisted `User`.

`app.api.routes.auth` only coordinates HTTP input, service calls, and response mapping. A future
SSO integration replaces the authentication-provider implementation and dependency wiring
without changing JWT-protected routes or current-user lookup.

## API Contract

### POST `/api/auth/login`

Request:

```json
{
  "email": "student@skku.edu",
  "password": "password123"
}
```

Success response, HTTP 200:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": {
    "id": "<user-id>",
    "name": "SKKU Student",
    "email": "student@skku.edu",
    "role": "student"
  }
}
```

The service normalizes the email with whitespace trimming and lowercasing before lookup. Local
authentication requires a non-null `password_hash`; external-only accounts cannot log in with a
password.

Unknown email, missing local password hash, and incorrect password all return the same response:

```json
{
  "detail": "Invalid email or password"
}
```

The status is HTTP 401 and the response includes `WWW-Authenticate: Bearer`.

### GET `/api/auth/me`

The endpoint requires:

```text
Authorization: Bearer <access-token>
```

It returns the same four-field user summary as login. Missing, malformed, expired, incorrectly
signed, wrong-type, or userless tokens return HTTP 401 with:

```json
{
  "detail": "Invalid or expired access token"
}
```

## JWT Contract

Access tokens use the configured algorithm, defaulting to `HS256`. Claims are:

- `sub`: persisted user ID
- `type`: `access`
- `iat`: issue time
- `exp`: expiration time

The lifetime comes from `JWT_EXPIRES_IN`, expressed in seconds and defaulting to `3600` for local
development. `JWT_SECRET` signs and verifies tokens. The example value remains suitable only for
local development; deployed environments must provide a long random secret.

Environment variables:

```text
JWT_SECRET=replace-with-a-long-random-secret
JWT_ALGORITHM=HS256
JWT_EXPIRES_IN=3600
```

## Components

### Security Module

`PasswordService` wraps Argon2 verification and treats malformed or unsupported hashes as a
failed credential check. `JWTService` creates and decodes only access tokens. JWT library errors
are translated to a single domain-level token error so HTTP details do not expose cryptographic
failure reasons.

### Authentication Provider

`AuthenticationProvider` is a protocol with an `authenticate(session, email, password)` method.
`LocalPasswordAuthProvider` queries by normalized email and delegates hash verification to
`PasswordService`. It returns `None` for every credential failure.

`AuthService` depends on an `AuthenticationProvider` and `JWTService`. Its login operation returns
an authenticated user and access token. The default FastAPI dependency builds it with the local
provider; future SSO wiring can supply another provider.

### Current-User Dependency

The dependency extracts an HTTP Bearer credential, decodes it, validates the `access` type and
subject, and then loads the user from the database. Protected endpoints receive the ORM `User`,
not caller-supplied IDs.

## Error and Security Behavior

- Passwords are never returned, logged, or compared as plaintext database values.
- Login does not reveal whether the email or password was incorrect.
- Token decoding restricts the accepted algorithm to the configured algorithm.
- `/me` always reloads the user, so deleted users immediately lose access.
- Authentication failures use HTTP 401 and `WWW-Authenticate: Bearer`.
- Pydantic validation failures remain the project's standard HTTP 422 responses.

## Testing

Tests use an isolated SQLite database, apply the real SQLAlchemy schema, and create users with
real Argon2 hashes. FastAPI database dependencies are overridden per test.

Coverage includes:

- successful login for admin, professor, and student Seed credentials
- response contract and access-token claims
- normalized email lookup
- identical 401 responses for unknown email, wrong password, and external-only users
- successful `/api/auth/me` lookup
- missing, malformed, expired, wrong-type, and unknown-user tokens
- unchanged health endpoint behavior
- Ruff, mypy, backend pytest, frontend typecheck, and frontend lint
