# Stage 2 Database and Seed Design

## Goal

Provide the persistent database foundation for stage 2 authentication, role-based access,
course management, and course-material uploads without implementing document parsing,
chunking, embeddings, or chat persistence.

## Scope

The initial schema contains exactly four tables:

- `users`
- `courses`
- `course_access`
- `course_materials`

The existing `DocumentChunk`, `ChatSession`, and `ChatLog` SQLAlchemy models and model
exports will be removed. Their Pydantic and shared TypeScript API types remain because the
current stub API and frontend use them without database persistence.

## Architecture

SQLAlchemy 2.x declarative models are the application-level schema source. Alembic owns
database creation and schema evolution. A Python seed command uses the same SQLAlchemy
session configuration as the backend and is idempotent so it can be run repeatedly in local
development.

PostgreSQL with psycopg is the target database. UUID values are represented as 36-character
strings to preserve the repository's current public ID shape and avoid an unrelated API
contract migration.

## Data Model

### User

- `id`: string UUID primary key
- `name`: required string
- `email`: required, unique, indexed string
- `password_hash`: nullable string for local accounts
- `external_auth_id`: nullable, unique, indexed string for future SSO accounts
- `school_id`: nullable, unique, indexed string
- `role`: required enum with `student`, `professor`, and `admin`
- `created_at`, `updated_at`: timezone-aware timestamps managed by the database

At least one of `password_hash` and `external_auth_id` is required through a database check
constraint. Seed users use local Argon2 password hashes.

### Course

- `id`: string UUID primary key
- `name`: required string
- `semester`: required, indexed string
- `description`: nullable text
- `professor_id`: required foreign key to `users.id`
- `is_active`: required boolean, default `true`
- `created_at`, `updated_at`: timezone-aware timestamps

The professor relationship is explicit. Role validation for the referenced user is enforced
by application services in the next authentication/course-management slice because a normal
foreign key cannot constrain another row's enum value.

### CourseAccess

- `id`: string UUID primary key
- `course_id`: required indexed foreign key to `courses.id`
- `user_id`: required indexed foreign key to `users.id`
- `access_role`: required string, default `student`
- `created_at`: timezone-aware timestamp

`UNIQUE(course_id, user_id)` prevents duplicate enrollment. `access_role` remains a string so
future values such as `ta` can be introduced without a database enum migration.

### CourseMaterial

- `id`: string UUID primary key
- `course_id`: required indexed foreign key to `courses.id`
- `uploaded_by`: required indexed foreign key to `users.id`
- `file_name`: required UUID-based internal filename
- `original_file_name`: required user-facing filename
- `file_type`: required extension or normalized type
- `file_size`: required non-negative bigint
- `storage_path`: required text path
- `processing_status`: required enum with `pending`, `processing`, `completed`, and `failed`
- `processing_error`: nullable text
- `created_at`, `updated_at`: timezone-aware timestamps

A check constraint rejects negative `file_size` values. No material rows are seeded because
no files exist yet.

## Migration

Alembic configuration lives under `apps/backend`. The initial stage-2 revision creates the
four tables, enum types, unique constraints, checks, indexes, and foreign keys. Downgrade
drops tables in dependency order and removes the PostgreSQL enum types.

The repository's pgvector initialization remains unchanged; no vector or document-chunk
table is created in this phase.

## Seed Data

The seed command creates or reconciles these accounts:

| Name | Email | School ID | Role | Password |
| --- | --- | --- | --- | --- |
| SKKU Admin | `admin@skku.edu` | `ADMIN001` | `admin` | `password123` |
| SKKU Professor | `professor@skku.edu` | `PROF001` | `professor` | `password123` |
| SKKU Student | `student@skku.edu` | `STUDENT001` | `student` | `password123` |

It also creates active `2026-2` courses named `인공지능개론` and `소프트웨어공학`, assigns
both to the seeded professor, and grants the seeded student access to both. Re-running the
seed command updates the expected demo values and does not create duplicates.

## Error Handling and Transactions

The seed operation runs in one transaction. A failure rolls back all seed changes. Missing
database tables produce an actionable message instructing the developer to run Alembic first.
Passwords are never stored or logged in plaintext; only an Argon2 hash is persisted.

## Testing and Verification

Automated tests cover:

- exact role and material-status enum values
- expected model columns, foreign keys, defaults, and constraints
- removal of future-stage ORM models from SQLAlchemy metadata
- idempotent seed creation of three users, two courses, and two access rows
- verification that `password123` matches every seeded Argon2 hash
- an empty but ready `course_materials` table

Final verification runs backend pytest and Ruff, upgrades a clean PostgreSQL database to the
latest Alembic revision, executes the seed twice, and queries row counts and relationships.

