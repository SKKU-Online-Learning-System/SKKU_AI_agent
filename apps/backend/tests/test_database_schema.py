from sqlalchemy import CheckConstraint, UniqueConstraint

from app.models.domain import Base, ChatAnswerSourceType, CourseMaterialStatus, UserRole


def test_metadata_contains_only_expected_tables() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "courses",
        "course_access",
        "course_materials",
        "document_chunks",
        "chat_sessions",
        "chat_logs",
    }


def test_stage_two_enum_values_match_contract() -> None:
    assert [role.value for role in UserRole] == ["student", "professor", "admin"]
    assert [status.value for status in CourseMaterialStatus] == [
        "pending",
        "processing",
        "completed",
        "failed",
    ]


def test_answer_source_type_values_match_contract() -> None:
    assert [source.value for source in ChatAnswerSourceType] == [
        "rag",
        "general_llm",
        "safety_response",
        "no_material",
    ]


def test_document_chunk_matches_retrieval_contract() -> None:
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
        "embedded_at",
        "created_at",
        "updated_at",
    } == set(table.columns.keys())

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("material_id", "chunk_index") in unique_columns


def test_chat_log_stores_answer_provenance() -> None:
    table = Base.metadata.tables["chat_logs"]

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
        "answer_source_type",
        "safety_result",
        "retrieval_result",
        "created_at",
    } == set(table.columns.keys())


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
        "embedded_at",
        "created_at",
        "updated_at",
    } == set(table.columns.keys())
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("material_id", "chunk_index") in unique_columns


def test_chat_storage_matches_stage_four_contract() -> None:
    session_table = Base.metadata.tables["chat_sessions"]
    log_table = Base.metadata.tables["chat_logs"]

    assert set(session_table.columns.keys()) == {
        "id",
        "user_id",
        "course_id",
        "title",
        "created_at",
        "updated_at",
    }
    assert set(log_table.columns.keys()) == {
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
        "answer_source_type",
        "created_at",
    }
    assert all(session_table.columns[name].foreign_keys for name in ("user_id", "course_id"))
    assert all(
        log_table.columns[name].foreign_keys
        for name in ("session_id", "user_id", "course_id")
    )
