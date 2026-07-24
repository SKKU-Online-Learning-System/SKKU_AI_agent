from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.domain import Base, CourseMaterialStatus, UserRole


def test_metadata_contains_expected_stage_three_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "courses",
        "course_access",
        "course_materials",
        "document_chunks",
    }


def test_stage_two_enum_values_match_contract() -> None:
    assert [role.value for role in UserRole] == ["student", "professor", "admin"]
    assert [status.value for status in CourseMaterialStatus] == [
        "pending",
        "processing",
        "completed",
        "failed",
    ]


def test_user_supports_local_and_external_authentication() -> None:
    table = Base.metadata.tables["users"]

    assert {
        "id",
        "name",
        "email",
        "password_hash",
        "external_auth_id",
        "school_id",
        "role",
        "created_at",
        "updated_at",
    } == set(table.columns.keys())

    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_users_auth_identity" in check_names


def test_course_matches_stage_two_contract() -> None:
    table = Base.metadata.tables["courses"]

    assert {
        "id",
        "name",
        "semester",
        "description",
        "professor_id",
        "is_active",
        "created_at",
        "updated_at",
    } == set(table.columns.keys())
    assert table.columns["professor_id"].foreign_keys


def test_course_access_prevents_duplicate_user_course_pairs() -> None:
    table = Base.metadata.tables["course_access"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("course_id", "user_id") in unique_columns


def test_material_metadata_matches_stage_two_contract() -> None:
    table = Base.metadata.tables["course_materials"]

    assert {
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
    } == set(table.columns.keys())

    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_course_materials_file_size_non_negative" in check_names
    assert "ck_course_materials_week_range" in check_names
    assert table.columns["processing_status"].default.arg == CourseMaterialStatus.pending


def test_document_chunk_matches_processing_contract() -> None:
    table = Base.metadata.tables["document_chunks"]

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
    } == set(table.columns.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("material_id", "chunk_index") in unique_columns
