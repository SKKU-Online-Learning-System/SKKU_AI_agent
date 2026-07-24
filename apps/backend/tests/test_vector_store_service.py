from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.models import (
    Base,
    Course,
    CourseMaterial,
    CourseMaterialStatus,
    DocumentChunk,
    User,
    UserRole,
)
from app.services.vector_store_service import (
    SQLAlchemyLocalVectorStoreService,
    VectorSearchError,
    cosine_similarity,
    create_vector_store_service,
)


@pytest.fixture
def vector_db() -> Generator[tuple[Session, dict[str, str]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    first_professor = User(
        name="First Professor",
        email="vector-first@skku.edu",
        external_auth_id="vector-first",
        role=UserRole.professor,
    )
    second_professor = User(
        name="Second Professor",
        email="vector-second@skku.edu",
        external_auth_id="vector-second",
        role=UserRole.professor,
    )
    session.add_all([first_professor, second_professor])
    session.flush()
    first_course = Course(
        name="First Course",
        semester="2026-2",
        professor_id=first_professor.id,
    )
    second_course = Course(
        name="Second Course",
        semester="2026-2",
        professor_id=second_professor.id,
    )
    session.add_all([first_course, second_course])
    session.flush()
    first_material = CourseMaterial(
        course_id=first_course.id,
        uploaded_by=first_professor.id,
        file_name="first.txt",
        original_file_name="first-lecture.txt",
        file_type="txt",
        file_size=10,
        storage_path="uploads/first.txt",
        processing_status=CourseMaterialStatus.completed,
    )
    second_material = CourseMaterial(
        course_id=second_course.id,
        uploaded_by=second_professor.id,
        file_name="second.txt",
        original_file_name="second-lecture.txt",
        file_type="txt",
        file_size=10,
        storage_path="uploads/second.txt",
        processing_status=CourseMaterialStatus.completed,
    )
    session.add_all([first_material, second_material])
    session.commit()
    ids = {
        "first_course": first_course.id,
        "second_course": second_course.id,
        "first_material": first_material.id,
        "second_material": second_material.id,
    }
    try:
        yield session, ids
    finally:
        session.close()


def chunk(
    *,
    chunk_id: str,
    course_id: str,
    material_id: str,
    chunk_index: int,
    text: str,
    embedding: list[float] | None,
) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        course_id=course_id,
        material_id=material_id,
        chunk_index=chunk_index,
        chunk_text=text,
        page_number=chunk_index + 1,
        section_title=None,
        char_count=len(text),
        embedding=embedding,
        embedding_model="test-model" if embedding is not None else None,
    )


def test_local_search_filters_course_embedding_threshold_and_top_k(
    vector_db: tuple[Session, dict[str, str]],
) -> None:
    session, ids = vector_db
    service = SQLAlchemyLocalVectorStoreService(session, score_threshold=0.3)
    service.upsert_chunks(
        [
            chunk(
                chunk_id="exact",
                course_id=ids["first_course"],
                material_id=ids["first_material"],
                chunk_index=0,
                text="exact match",
                embedding=[1.0, 0.0],
            ),
            chunk(
                chunk_id="near",
                course_id=ids["first_course"],
                material_id=ids["first_material"],
                chunk_index=1,
                text="near match",
                embedding=[0.8, 0.6],
            ),
            chunk(
                chunk_id="missing",
                course_id=ids["first_course"],
                material_id=ids["first_material"],
                chunk_index=2,
                text="missing embedding",
                embedding=None,
            ),
            chunk(
                chunk_id="wrong-dimension",
                course_id=ids["first_course"],
                material_id=ids["first_material"],
                chunk_index=3,
                text="wrong dimension",
                embedding=[1.0, 0.0, 0.0],
            ),
            chunk(
                chunk_id="other-course",
                course_id=ids["second_course"],
                material_id=ids["second_material"],
                chunk_index=0,
                text="must never leak",
                embedding=[1.0, 0.0],
            ),
            chunk(
                chunk_id="mismatched-material-course",
                course_id=ids["first_course"],
                material_id=ids["second_material"],
                chunk_index=1,
                text="must also never leak",
                embedding=[1.0, 0.0],
            ),
        ]
    )
    session.commit()

    results = service.search_similar_chunks(
        ids["first_course"],
        [1.0, 0.0],
    )

    assert [result.chunk_id for result in results] == ["exact", "near"]
    assert [result.score for result in results] == pytest.approx([1.0, 0.8])
    assert all(result.course_id == ids["first_course"] for result in results)
    assert results[0].document_name == "first-lecture.txt"
    assert results[0].page_number == 1
    assert results[0].chunk_text == "exact match"
    assert service.search_similar_chunks(
        ids["first_course"],
        [1.0, 0.0],
        top_k=1,
    )[0].chunk_id == "exact"


def test_threshold_upsert_and_delete_are_repository_scoped(
    vector_db: tuple[Session, dict[str, str]],
) -> None:
    session, ids = vector_db
    service = SQLAlchemyLocalVectorStoreService(session, score_threshold=0.9)
    original = chunk(
        chunk_id="replace-me",
        course_id=ids["first_course"],
        material_id=ids["first_material"],
        chunk_index=0,
        text="old text",
        embedding=[1.0, 0.0],
    )
    other = chunk(
        chunk_id="keep-me",
        course_id=ids["second_course"],
        material_id=ids["second_material"],
        chunk_index=0,
        text="other material",
        embedding=[1.0, 0.0],
    )
    service.upsert_chunks([original, other])
    session.commit()
    replacement = chunk(
        chunk_id="replace-me",
        course_id=ids["first_course"],
        material_id=ids["first_material"],
        chunk_index=0,
        text="new text",
        embedding=[0.8, 0.6],
    )
    service.upsert_chunks([replacement])
    session.commit()

    assert service.search_similar_chunks(
        ids["first_course"],
        [1.0, 0.0],
    ) == []
    assert session.get(DocumentChunk, "replace-me").chunk_text == "new text"

    service.delete_chunks_by_material(ids["first_material"])
    session.commit()

    assert session.get(DocumentChunk, "replace-me") is None
    assert session.get(DocumentChunk, "keep-me") is not None


@pytest.mark.parametrize("top_k", [0, 21])
def test_top_k_is_bounded(
    vector_db: tuple[Session, dict[str, str]],
    top_k: int,
) -> None:
    session, ids = vector_db

    with pytest.raises(VectorSearchError, match="VECTOR_TOP_K_INVALID"):
        SQLAlchemyLocalVectorStoreService(session).search_similar_chunks(
            ids["first_course"],
            [1.0],
            top_k=top_k,
        )


def test_cosine_similarity_handles_normal_and_zero_vectors() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 0.0]) == 0.0


def test_factory_selects_local_and_rejects_unavailable_pgvector(
    vector_db: tuple[Session, dict[str, str]],
) -> None:
    session, _ = vector_db

    local = create_vector_store_service(
        session,
        Settings(
            vector_search_mode="local",
            rag_top_k=3,
            rag_score_threshold=0.4,
        ),
    )

    assert isinstance(local, SQLAlchemyLocalVectorStoreService)
    with pytest.raises(VectorSearchError, match="VECTOR_SEARCH_MODE_UNAVAILABLE"):
        create_vector_store_service(
            session,
            Settings(vector_search_mode="pgvector"),
        )
