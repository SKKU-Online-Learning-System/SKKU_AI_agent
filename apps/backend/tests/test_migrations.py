from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.models import User, UserRole


def test_alembic_upgrade_and_downgrade_full_schema(tmp_path: Path) -> None:
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "migration.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    inspector = inspect(create_engine(database_url))
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "users",
        "courses",
        "course_access",
        "course_materials",
        "document_chunks",
        "chat_sessions",
        "chat_logs",
        "login_events",
        "revoked_access_tokens",
    }
    chunk_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
    assert {
        "course_id",
        "material_id",
        "chunk_index",
        "embedding",
        "embedded_at",
        "page_number",
    } <= chunk_columns
    log_columns = {column["name"] for column in inspector.get_columns("chat_logs")}
    assert {
        "referenced_documents",
        "safety_result",
        "retrieval_result",
        "is_grounded",
        "answer_source_type",
        "prompt_tokens",
        "completion_tokens",
    } <= log_columns
    material_columns = {
        column["name"]: column for column in inspector.get_columns("course_materials")
    }
    assert set(material_columns) == {
        "id",
        "course_id",
        "uploaded_by",
        "file_name",
        "original_file_name",
        "file_type",
        "file_size",
        "week",
        "storage_path",
        "processing_status",
        "processing_error",
        "created_at",
        "updated_at",
    }
    assert material_columns["processing_status"]["default"] == "'pending'"
    assert material_columns["week"]["default"] == "'1'"
    chunk_columns = {
        column["name"] for column in inspector.get_columns("document_chunks")
    }
    assert {
        "id",
        "course_id",
        "material_id",
        "chunk_index",
        "chunk_text",
        "page_number",
        "section_title",
        "char_count",
        "embedding",
        "embedding_model",
        "page_image",
        "page_evidence",
        "page_note",
        "embedded_at",
        "created_at",
        "updated_at",
    } == chunk_columns
    assert {
        "id",
        "user_id",
        "course_id",
        "title",
        "created_at",
        "updated_at",
    } == {column["name"] for column in inspector.get_columns("chat_sessions")}
    assert {
        "id",
        "session_id",
        "user_id",
        "course_id",
        "question",
        "answer",
        "referenced_documents",
        "model_name",
        "response_time_ms",
        "prompt_tokens",
        "completion_tokens",
        "is_grounded",
        "safety_result",
        "retrieval_result",
        "answer_source_type",
        "created_at",
    } == {column["name"] for column in inspector.get_columns("chat_logs")}

    command.downgrade(config, "base")

    assert inspect(create_engine(database_url)).get_table_names() == ["alembic_version"]


@pytest.mark.parametrize("old_revision", ["20260907_0007", "20261027_0009", "20261110_0010"])
def test_existing_migration_histories_join_without_losing_rows(
    tmp_path: Path, old_revision: str,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'existing.sqlite').as_posix()}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, old_revision)
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            session.add(User(
                name="Existing user", email="existing@example.test",
                external_auth_id="existing", role=UserRole.student,
            ))
            session.commit()

        command.upgrade(config, "head")
        command.current(config, check_heads=True)

        with Session(engine) as session:
            assert session.scalar(select(User.email)) == "existing@example.test"
        inspector = inspect(engine)
        assert "revoked_access_tokens" in inspector.get_table_names()
        assert "page_note" in {col["name"] for col in inspector.get_columns("document_chunks")}
        assert "ix_chat_logs_course_id_created_at" in {
            index["name"] for index in inspector.get_indexes("chat_logs")
        }
    finally:
        engine.dispose()
