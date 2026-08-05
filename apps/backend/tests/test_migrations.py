from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
    }
    chunk_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
    assert {"course_id", "material_id", "chunk_index", "embedding", "page_number"} <= chunk_columns
    log_columns = {column["name"] for column in inspector.get_columns("chat_logs")}
    assert {
        "referenced_documents",
        "safety_result",
        "retrieval_result",
        "is_grounded",
        "answer_source_type",
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
        "is_grounded",
        "safety_result",
        "retrieval_result",
        "created_at",
    } == {column["name"] for column in inspector.get_columns("chat_logs")}

    command.downgrade(config, "base")

    assert inspect(create_engine(database_url)).get_table_names() == ["alembic_version"]
