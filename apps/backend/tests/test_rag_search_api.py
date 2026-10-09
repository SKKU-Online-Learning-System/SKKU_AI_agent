from collections.abc import Generator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.security import JWTService
from app.db.session import get_db
from app.main import app
from app.models import (
    Base,
    Course,
    CourseAccess,
    CourseMaterial,
    CourseMaterialStatus,
    DocumentChunk,
    User,
    UserRole,
)
from app.services.embedding_service import EmbeddingService
from app.services.vector_store_service import VectorStoreService


@dataclass(frozen=True)
class RAGApiContext:
    client: TestClient
    tokens: dict[str, str]
    courses: dict[str, str]

    def headers(self, user: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[user]}"}


def add_user(session: Session, name: str, role: UserRole) -> User:
    user = User(
        name=name,
        email=f"{name}@skku.edu",
        external_auth_id=f"external-{name}",
        role=role,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def rag_api() -> Generator[RAGApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    settings = Settings(
        embedding_provider="mock",
        rag_text_score_threshold=0.1,
        vector_db_embedding_dim=16,
        mock_embedding_dim=128,
        rag_score_threshold=0.3,
        _env_file=None,
    )

    with testing_session() as session:
        users = {
            "admin": add_user(session, "admin-rag", UserRole.admin),
            "professor": add_user(session, "professor-rag", UserRole.professor),
            "other_professor": add_user(session, "other-professor-rag", UserRole.professor),
            "student": add_user(session, "student-rag", UserRole.student),
        }
        courses = {
            "owned": Course(
                name="Owned", semester="2026-2", professor_id=users["professor"].id
            ),
            "other": Course(
                name="Other", semester="2026-2", professor_id=users["other_professor"].id
            ),
            "inactive": Course(
                name="Inactive",
                semester="2026-2",
                professor_id=users["professor"].id,
                is_active=False,
            ),
            "empty": Course(
                name="Empty", semester="2026-2", professor_id=users["professor"].id
            ),
        }
        session.add_all(courses.values())
        session.flush()
        session.add_all(
            [
                CourseAccess(course_id=courses["owned"].id, user_id=users["student"].id),
                CourseAccess(course_id=courses["inactive"].id, user_id=users["student"].id),
            ]
        )

        materials = {
            "owned": CourseMaterial(
                course_id=courses["owned"].id,
                uploaded_by=users["professor"].id,
                file_name="owned.pdf",
                original_file_name="lecture1.pdf",
                file_type="pdf",
                file_size=10,
                storage_path="owned.pdf",
                processing_status=CourseMaterialStatus.completed,
            ),
            "failed": CourseMaterial(
                course_id=courses["owned"].id,
                uploaded_by=users["professor"].id,
                file_name="failed.pdf",
                original_file_name="failed.pdf",
                file_type="pdf",
                file_size=10,
                storage_path="failed.pdf",
                processing_status=CourseMaterialStatus.failed,
            ),
            "pending": CourseMaterial(
                course_id=courses["owned"].id,
                uploaded_by=users["professor"].id,
                file_name="pending.pdf",
                original_file_name="pending.pdf",
                file_type="pdf",
                file_size=10,
                storage_path="pending.pdf",
                processing_status=CourseMaterialStatus.pending,
            ),
            "other": CourseMaterial(
                course_id=courses["other"].id,
                uploaded_by=users["other_professor"].id,
                file_name="other.pdf",
                original_file_name="other.pdf",
                file_type="pdf",
                file_size=10,
                storage_path="other.pdf",
                processing_status=CourseMaterialStatus.completed,
            ),
            "empty": CourseMaterial(
                course_id=courses["empty"].id,
                uploaded_by=users["professor"].id,
                file_name="empty.pdf",
                original_file_name="empty.pdf",
                file_type="pdf",
                file_size=10,
                storage_path="empty.pdf",
                processing_status=CourseMaterialStatus.pending,
            ),
        }
        session.add_all(materials.values())
        session.flush()
        texts = ["gradient descent basics", "neural networks", "failed gradient", "other secret"]
        embedder = EmbeddingService(settings)
        embeddings = embedder.embed_texts(texts)
        session.add_all(
            [
                DocumentChunk(
                    course_id=courses["owned"].id,
                    material_id=materials["owned"].id,
                    chunk_index=0,
                    chunk_text=texts[0],
                    char_count=len(texts[0]),
                    page_number=12,
                    embedding=embeddings[0],
                    embedding_model=embedder.model_name,
                ),
                DocumentChunk(
                    course_id=courses["owned"].id,
                    material_id=materials["owned"].id,
                    chunk_index=1,
                    chunk_text=texts[1],
                    char_count=len(texts[1]),
                    embedding=embeddings[1],
                    embedding_model=embedder.model_name,
                ),
                DocumentChunk(
                    course_id=courses["owned"].id,
                    material_id=materials["owned"].id,
                    chunk_index=2,
                    chunk_text="not embedded",
                    char_count=len("not embedded"),
                ),
                DocumentChunk(
                    course_id=courses["owned"].id,
                    material_id=materials["failed"].id,
                    chunk_index=0,
                    chunk_text=texts[2],
                    char_count=len(texts[2]),
                    embedding=embeddings[2],
                    embedding_model=embedder.model_name,
                ),
                DocumentChunk(
                    course_id=courses["other"].id,
                    material_id=materials["other"].id,
                    chunk_index=0,
                    chunk_text=texts[3],
                    char_count=len(texts[3]),
                    embedding=embeddings[3],
                    embedding_model=embedder.model_name,
                ),
            ]
        )
        session.commit()
        user_ids = {name: user.id for name, user in users.items()}
        course_ids = {name: course.id for name, course in courses.items()}

    token_service = JWTService(
        settings.jwt_secret, settings.jwt_algorithm, settings.jwt_expires_in
    )
    tokens = {
        name: token_service.create_access_token(user_id) for name, user_id in user_ids.items()
    }

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield RAGApiContext(client=client, tokens=tokens, courses=course_ids)
    app.dependency_overrides.clear()


def test_search_returns_top_k_only_from_accessible_course(rag_api: RAGApiContext) -> None:
    response = rag_api.client.post(
        "/api/rag/search",
        headers=rag_api.headers("student"),
        json={"course_id": rag_api.courses["owned"], "question": "gradient descent", "top_k": 1},
    )

    assert response.status_code == 200
    assert response.json() == {
        "courseId": rag_api.courses["owned"],
        "question": "gradient descent",
        "topK": 1,
        "results": [
            {
                "chunkId": response.json()["results"][0]["chunkId"],
                "materialId": response.json()["results"][0]["materialId"],
                "documentName": "lecture1.pdf",
                "pageNumber": 12,
                "chunkIndex": 0,
                "chunkText": "gradient descent basics",
                "pageImageUrl": None,
                "score": response.json()["results"][0]["score"],
            }
        ],
        "debug": None,
    }


def test_search_enforces_role_course_access_and_validation(rag_api: RAGApiContext) -> None:
    payload = {"course_id": rag_api.courses["other"], "question": "other secret"}

    assert rag_api.client.post("/api/rag/search", json=payload).status_code == 401
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("student"), json=payload
        ).status_code
        == 403
    )
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("professor"), json=payload
        ).status_code
        == 403
    )
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("other_professor"), json=payload
        ).status_code
        == 200
    )
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("admin"), json=payload
        ).status_code
        == 200
    )
    inactive = {"course_id": rag_api.courses["inactive"], "question": "question"}
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("student"), json=inactive
        ).status_code
        == 403
    )
    missing = {"course_id": "missing", "question": "question"}
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("admin"), json=missing
        ).status_code
        == 404
    )
    invalid = {"course_id": rag_api.courses["owned"], "question": "   ", "top_k": 21}
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("student"), json=invalid
        ).status_code
        == 422
    )


def test_debug_search_is_professor_only_and_reports_filtered_candidates(
    rag_api: RAGApiContext,
) -> None:
    payload = {
        "course_id": rag_api.courses["owned"],
        "question": "gradient descent",
        "debug": True,
    }

    response = rag_api.client.post(
        "/api/rag/search", headers=rag_api.headers("professor"), json=payload
    )

    assert response.status_code == 200
    assert response.json()["debug"] == {
        "embeddingModel": "mock-hash-128",
        "searchMode": "local",
        "scoreThreshold": 0.3,
        "textScoreThreshold": 0.1,
        "totalCandidateChunks": 2,
    }
    assert all(result["documentName"] == "lecture1.pdf" for result in response.json()["results"])
    assert (
        rag_api.client.post(
            "/api/rag/search", headers=rag_api.headers("student"), json=payload
        ).status_code
        == 200
    )


def test_rag_status_counts_chunks_and_requires_access(rag_api: RAGApiContext) -> None:
    owned_url = f"/api/courses/{rag_api.courses['owned']}/rag/status"
    response = rag_api.client.get(owned_url, headers=rag_api.headers("student"))

    assert response.status_code == 200
    assert response.json() == {
        "courseId": rag_api.courses["owned"],
        "materialCount": 3,
        "completedMaterialCount": 1,
        "failedMaterialCount": 1,
        "pendingMaterialCount": 1,
        "chunkCount": 4,
        "embeddedChunkCount": 3,
        "isSearchReady": True,
    }
    empty_url = f"/api/courses/{rag_api.courses['empty']}/rag/status"
    assert rag_api.client.get(empty_url, headers=rag_api.headers("professor")).json()[
        "isSearchReady"
    ] is False
    empty_search = rag_api.client.post(
        "/api/rag/search",
        headers=rag_api.headers("professor"),
        json={"course_id": rag_api.courses["empty"], "question": "anything"},
    )
    assert empty_search.status_code == 200
    assert empty_search.json()["results"] == []
    assert rag_api.client.get(empty_url, headers=rag_api.headers("student")).status_code == 403


def test_search_failures_return_stable_error_code(
    rag_api: RAGApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_search(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("vector store unavailable")

    monkeypatch.setattr(
        VectorStoreService,
        "search_similar_chunks",
        fail_search,
    )
    response = rag_api.client.post(
        "/api/rag/search",
        headers=rag_api.headers("student"),
        json={"course_id": rag_api.courses["owned"], "question": "gradient"},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "RAG_SEARCH_FAILED"


def test_embedding_failures_return_stable_error_code(
    rag_api: RAGApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_embedding(*args: object, **kwargs: object) -> list[float]:
        raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(EmbeddingService, "embed_text", fail_embedding)
    response = rag_api.client.post(
        "/api/rag/search",
        headers=rag_api.headers("student"),
        json={"course_id": rag_api.courses["owned"], "question": "gradient"},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "RAG_SEARCH_FAILED"
