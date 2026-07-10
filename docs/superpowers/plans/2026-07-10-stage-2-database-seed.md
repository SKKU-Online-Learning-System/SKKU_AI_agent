# Stage 2 Database and Seed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the stage-2 PostgreSQL schema, Alembic migration, and idempotent demo seed data for users, courses, course access, and course-material metadata.

**Architecture:** Keep SQLAlchemy 2.x declarative models as the application schema and use Alembic for database lifecycle. Add an injectable seed function that operates on a SQLAlchemy `Session`, plus a module CLI and Make targets for local use. Future-stage document chunks and chat persistence are removed from ORM metadata.

**Tech Stack:** Python 3.9+, SQLAlchemy 2.x, Alembic 1.x, PostgreSQL 16/psycopg 3, argon2-cffi, pytest, Ruff.

## Global Constraints

- Preserve the existing `apps/backend/app` package structure and SQLAlchemy style.
- Roles are exactly `student`, `professor`, and `admin`.
- Material statuses are exactly `pending`, `processing`, `completed`, and `failed`.
- The initial migration creates only `users`, `courses`, `course_access`, and `course_materials`.
- Do not implement document parsing, chunks, embeddings, vector persistence, or chat persistence.
- IDs remain 36-character UUID strings to preserve current API shapes.
- Python code uses 4-space indentation, type hints where useful, and Ruff line length 100.

---

### Task 1: Stage-2 SQLAlchemy Schema

**Files:**
- Modify: `apps/backend/app/models/domain.py`
- Modify: `apps/backend/app/models/__init__.py`
- Test: `apps/backend/tests/test_database_schema.py`

**Interfaces:**
- Produces: `UserRole`, `CourseMaterialStatus`, `User`, `Course`, `CourseAccess`, and `CourseMaterial`.
- Produces: `Base.metadata` containing exactly four stage-2 tables.
- Consumes: SQLAlchemy declarative base and the repository's UUID-string ID convention.

- [ ] **Step 1: Write failing metadata tests**

Create `apps/backend/tests/test_database_schema.py` with tests that assert:

```python
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.domain import Base, CourseMaterialStatus, UserRole


def test_stage_two_metadata_contains_only_expected_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "courses",
        "course_access",
        "course_materials",
    }


def test_stage_two_enum_values_match_contract() -> None:
    assert [role.value for role in UserRole] == ["student", "professor", "admin"]
    assert [status.value for status in CourseMaterialStatus] == [
        "pending",
        "processing",
        "completed",
        "failed",
    ]


def test_course_access_prevents_duplicate_user_course_pairs() -> None:
    table = Base.metadata.tables["course_access"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("course_id", "user_id") in unique_columns


def test_material_file_size_has_non_negative_check() -> None:
    table = Base.metadata.tables["course_materials"]
    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_course_materials_file_size_non_negative" in check_names
```

- [ ] **Step 2: Run the schema tests and confirm the expected failure**

Run:

```powershell
python -m pytest apps/backend/tests/test_database_schema.py -q -p no:cacheprovider
```

Expected: failure because ORM metadata still contains future-stage tables and enum values still use `instructor`, `uploaded`, and `ready`.

- [ ] **Step 3: Replace the ORM schema with the approved four-table model**

Implement the following model contract in `domain.py`:

```python
class UserRole(str, Enum):
    student = "student"
    professor = "professor"
    admin = "admin"


class CourseMaterialStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
```

Use named constraints and non-native SQLAlchemy enums:

```python
SQLEnum(
    UserRole,
    name="user_role",
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
)
```

Implement these table rules:

- `users`: unique/indexed email, school ID, and external auth ID; check that either
  `password_hash` or `external_auth_id` is present.
- `courses`: professor FK, description, semester, active flag, and timestamps.
- `course_access`: cascade FKs, indexed user/course IDs, unique user/course pair.
- `course_materials`: course cascade FK, uploader restrict FK, non-negative bigint size,
  processing status, processing error, and timestamps.
- Remove `DocumentChunk`, `ChatSession`, and `ChatLog` from this file and from model exports.

- [ ] **Step 4: Run the schema tests and confirm they pass**

Run:

```powershell
python -m pytest apps/backend/tests/test_database_schema.py -q -p no:cacheprovider
```

Expected: all schema tests pass.

- [ ] **Step 5: Commit the schema slice**

```powershell
git add apps/backend/app/models apps/backend/tests/test_database_schema.py
git commit -m "Add stage 2 database models"
```

---

### Task 2: Alembic Migration

**Files:**
- Modify: `apps/backend/pyproject.toml`
- Create: `apps/backend/alembic.ini`
- Create: `apps/backend/alembic/env.py`
- Create: `apps/backend/alembic/script.py.mako`
- Create: `apps/backend/alembic/versions/20260710_0001_stage_2_schema.py`
- Test: `apps/backend/tests/test_migrations.py`

**Interfaces:**
- Consumes: `app.models.Base.metadata` and `app.core.config.Settings.database_url`.
- Produces: Alembic revision `20260710_0001` and the command `alembic upgrade head`.

- [ ] **Step 1: Write a failing migration test**

Create a test that upgrades a temporary SQLite database using Alembic and inspects the real
schema:

```python
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_only_stage_two_tables(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.sqlite"
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")

    command.upgrade(config, "head")

    tables = set(inspect(create_engine(f"sqlite:///{database_path.as_posix()}")).get_table_names())
    assert tables == {
        "alembic_version",
        "users",
        "courses",
        "course_access",
        "course_materials",
    }
```

- [ ] **Step 2: Run the migration test and confirm missing Alembic/config failure**

Run:

```powershell
python -m pytest apps/backend/tests/test_migrations.py -q -p no:cacheprovider
```

Expected: import or configuration failure because Alembic and migration files are absent.

- [ ] **Step 3: Add migration and password-hashing dependencies**

Add to backend runtime dependencies:

```toml
"alembic>=1.13,<2",
"argon2-cffi>=23.1,<26",
```

Install the editable backend development environment:

```powershell
python -m pip install -e "apps/backend[dev]"
```

- [ ] **Step 4: Add Alembic configuration and initial revision**

Configure `alembic/env.py` to use the URL supplied by Alembic tests when present and otherwise
fall back to `get_settings().database_url`. Set `target_metadata = Base.metadata`.

The revision must create tables in this order:

1. `users`
2. `courses`
3. `course_access`
4. `course_materials`

Use `sa.Enum(..., native_enum=False, create_constraint=True)` so the allowed values are
database checked and the same revision can be tested on SQLite. Downgrade drops the four
tables in reverse dependency order.

- [ ] **Step 5: Run migration upgrade/downgrade tests**

Extend the test to run `command.downgrade(config, "base")` and assert that no application
tables remain. Then run:

```powershell
python -m pytest apps/backend/tests/test_migrations.py -q -p no:cacheprovider
```

Expected: migration tests pass.

- [ ] **Step 6: Commit the migration slice**

```powershell
git add apps/backend/pyproject.toml apps/backend/alembic.ini apps/backend/alembic apps/backend/tests/test_migrations.py
git commit -m "Add stage 2 database migration"
```

---

### Task 3: Idempotent Demo Seed

**Files:**
- Create: `apps/backend/app/db/seed.py`
- Test: `apps/backend/tests/test_seed.py`

**Interfaces:**
- Produces: `seed_database(session: Session) -> SeedSummary`.
- Produces: `python -m app.db.seed` CLI.
- Consumes: `SessionLocal`, Argon2 `PasswordHasher`, and all four stage-2 models.

- [ ] **Step 1: Write a failing seed test**

Use a temporary SQLite database with foreign keys enabled. Create the schema, run the seed
twice, and assert exact counts and relationships:

```python
from argon2 import PasswordHasher
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.db.seed import seed_database
from app.models import Base, Course, CourseAccess, CourseMaterial, User


def test_seed_is_idempotent_and_creates_expected_demo_data() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_database(session)
        seed_database(session)

        assert session.scalar(select(func.count()).select_from(User)) == 3
        assert session.scalar(select(func.count()).select_from(Course)) == 2
        assert session.scalar(select(func.count()).select_from(CourseAccess)) == 2
        assert session.scalar(select(func.count()).select_from(CourseMaterial)) == 0

        professor = session.scalar(select(User).where(User.email == "professor@skku.edu"))
        student = session.scalar(select(User).where(User.email == "student@skku.edu"))
        courses = session.scalars(select(Course).order_by(Course.name)).all()

        assert professor is not None
        assert student is not None
        assert all(course.professor_id == professor.id for course in courses)
        assert {access.course_id for access in student.course_accesses} == {
            course.id for course in courses
        }

        hasher = PasswordHasher()
        for user in session.scalars(select(User)).all():
            assert user.password_hash is not None
            assert hasher.verify(user.password_hash, "password123")
```

- [ ] **Step 2: Run the seed test and confirm the missing module failure**

Run:

```powershell
python -m pytest apps/backend/tests/test_seed.py -q -p no:cacheprovider
```

Expected: failure because `app.db.seed` does not exist.

- [ ] **Step 3: Implement the minimal idempotent seed function and CLI**

Define immutable seed specifications for three users and two courses. Resolve users by email,
courses by `(name, semester, professor_id)`, and access rows by `(course_id, user_id)`.

Return:

```python
@dataclass(frozen=True)
class SeedSummary:
    users: int
    courses: int
    course_access: int
```

The CLI opens `SessionLocal`, runs the seed in one transaction, prints `users=3 courses=2
course_access=2`, and rolls back with a non-zero exit on failure. Catch missing-table database
errors and instruct the user to run `alembic upgrade head` first.

- [ ] **Step 4: Run seed tests and the complete backend suite**

Run:

```powershell
python -m pytest apps/backend/tests/test_seed.py -q -p no:cacheprovider
python -m pytest apps/backend/tests -q -p no:cacheprovider
```

Expected: seed test and all backend tests pass.

- [ ] **Step 5: Commit the seed slice**

```powershell
git add apps/backend/app/db/seed.py apps/backend/tests/test_seed.py
git commit -m "Add idempotent demo seed"
```

---

### Task 4: Developer Commands and Documentation

**Files:**
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `.env.example` only if database documentation requires clarification

**Interfaces:**
- Produces: `make migrate-db`, `make seed-db`, and documented direct PowerShell commands.
- Consumes: `apps/backend/alembic.ini` and `python -m app.db.seed`.

- [ ] **Step 1: Add Make targets**

Add:

```makefile
migrate-db:
	cd apps/backend && alembic upgrade head

seed-db:
	cd apps/backend && python -m app.db.seed
```

Include both names in `.PHONY`.

- [ ] **Step 2: Document migration, seed, and verification commands**

Update README local setup to show:

```powershell
make dev-db
make migrate-db
make seed-db
```

Also document Windows-friendly direct commands:

```powershell
cd apps/backend
python -m alembic upgrade head
python -m app.db.seed
```

List the three demo emails and state that the local-only password is `password123`.

- [ ] **Step 3: Run formatting and static verification**

Run:

```powershell
python -m ruff check apps/backend
python -m mypy apps/backend/app
python -m pytest apps/backend/tests -q -p no:cacheprovider
```

Expected: all commands exit 0.

- [ ] **Step 4: Commit documentation and command changes**

```powershell
git add Makefile README.md .env.example
git commit -m "Document database migration and seed"
```

---

### Task 5: PostgreSQL End-to-End Verification

**Files:**
- Verify only; modify implementation files only in response to a reproduced failing test.

**Interfaces:**
- Consumes: Docker Compose database, Alembic migration, and seed CLI.
- Produces: fresh evidence that the acceptance criteria work on PostgreSQL.

- [ ] **Step 1: Start PostgreSQL and wait for health**

```powershell
docker compose up -d db
docker compose ps db
```

Expected: `db` reports healthy.

- [ ] **Step 2: Recreate the schema through Alembic**

Use downgrade only on the local project database after confirming the target URL:

```powershell
cd apps/backend
python -m alembic downgrade base
python -m alembic upgrade head
```

Expected: both commands exit 0 and upgrade reaches revision `20260710_0001`.

- [ ] **Step 3: Execute the seed twice**

```powershell
python -m app.db.seed
python -m app.db.seed
```

Expected each time: `users=3 courses=2 course_access=2`.

- [ ] **Step 4: Query acceptance-criteria counts and assignments**

Run a SQLAlchemy verification command that reports:

```text
users=3
courses=2
course_access=2
course_materials=0
roles=admin,professor,student
```

Confirm both courses reference `professor@skku.edu` and both access rows reference
`student@skku.edu`.

- [ ] **Step 5: Run the full final verification suite**

From the repository root:

```powershell
python -m pytest apps/backend/tests -q -p no:cacheprovider
python -m ruff check apps/backend
python -m mypy apps/backend/app
npm.cmd run typecheck
npm.cmd run lint
git diff --check
git status --short
```

Expected: tests, static checks, frontend checks, and whitespace checks exit 0. `git status`
must contain only intentional changes or previously identified user-owned untracked files.
