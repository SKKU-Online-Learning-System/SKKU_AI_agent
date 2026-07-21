from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_and_downgrade_stage_two_schema(tmp_path: Path) -> None:
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
    }
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
    assert material_columns["processing_status"]["default"] == "'completed'"
    assert material_columns["week"]["default"] == "'1'"

    command.downgrade(config, "base")

    assert inspect(create_engine(database_url)).get_table_names() == ["alembic_version"]
