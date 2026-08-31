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
from app.models import Base, ChatLog, ChatSession, Course, CourseAccess, User, UserRole


@dataclass(frozen=True)
class ChatApiContext:
    client: TestClient
    session_factory: sessionmaker[Session]
    tokens: dict[str, str]
    users: dict[str, str]
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
def chat_api() -> Generator[ChatApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None)

    with testing_session() as session:
        student = add_user(session, "chat-student", UserRole.student)
        other_student = add_user(session, "other-chat-student", UserRole.student)
        professor = add_user(session, "chat-professor", UserRole.professor)
        owned = Course(
            name="Owned",
            semester="2026-2",
            professor_id=professor.id,
            is_active=True,
        )
        inaccessible = Course(
            name="Inaccessible",
            semester="2026-2",
            professor_id=professor.id,
            is_active=True,
        )
        session.add_all([owned, inaccessible])
        session.flush()
        session.add(CourseAccess(course_id=owned.id, user_id=student.id))
        session.commit()
        users = {"student": student.id, "other_student": other_student.id}
        courses = {"owned": owned.id, "inaccessible": inaccessible.id}

    jwt = JWTService(settings.jwt_secret, settings.jwt_algorithm, settings.jwt_expires_in)
    tokens = {name: jwt.create_access_token(user_id) for name, user_id in users.items()}

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield ChatApiContext(client, testing_session, tokens, users, courses)
    app.dependency_overrides.clear()


def create_session(chat_api: ChatApiContext) -> dict[str, object]:
    response = chat_api.client.post(
        "/api/chat/sessions",
        headers=chat_api.headers("student"),
        json={"course_id": chat_api.courses["owned"]},
    )
    assert response.status_code == 201
    return response.json()


def test_create_session_requires_authentication_and_course_access(
    chat_api: ChatApiContext,
) -> None:
    payload = {"course_id": chat_api.courses["owned"]}
    assert chat_api.client.post("/api/chat/sessions", json=payload).status_code == 401

    denied = chat_api.client.post(
        "/api/chat/sessions",
        headers=chat_api.headers("student"),
        json={"course_id": chat_api.courses["inaccessible"]},
    )
    created = create_session(chat_api)

    assert denied.status_code == 403
    assert created["userId"] == chat_api.users["student"]
    assert created["courseId"] == chat_api.courses["owned"]
    assert created["title"] is None
    with chat_api.session_factory() as session:
        assert session.get(ChatSession, created["id"]) is not None


def test_list_returns_only_current_users_sessions(chat_api: ChatApiContext) -> None:
    owned = create_session(chat_api)
    with chat_api.session_factory() as session:
        session.add(
            ChatSession(
                user_id=chat_api.users["other_student"],
                course_id=chat_api.courses["owned"],
            )
        )
        session.commit()

    response = chat_api.client.get(
        "/api/chat/sessions",
        headers=chat_api.headers("student"),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [owned["id"]]


def test_owner_can_read_session_with_logs_but_other_user_cannot(
    chat_api: ChatApiContext,
) -> None:
    created = create_session(chat_api)
    referenced_documents = [
        {
            "material_id": "material-1",
            "document_name": "lecture1.pdf",
            "page_number": 12,
            "chunk_index": 3,
            "score": 0.87,
        }
    ]
    with chat_api.session_factory() as session:
        session.add(
            ChatLog(
                session_id=created["id"],
                user_id=chat_api.users["student"],
                course_id=chat_api.courses["owned"],
                question="경사하강법이 뭐야?",
                answer="손실을 줄이는 최적화 방법입니다.",
                referenced_documents=referenced_documents,
                model_name="qwen3.8-27b",
                response_time_ms=120,
                is_grounded=True,
                safety_result={"blocked": False, "category": "normal", "reason": None},
                retrieval_result={
                    "top_k": 5,
                    "result_count": 1,
                    "max_score": 0.87,
                    "search_mode": "local",
                },
            )
        )
        session.commit()

    owner = chat_api.client.get(
        f"/api/chat/sessions/{created['id']}",
        headers=chat_api.headers("student"),
    )
    other = chat_api.client.get(
        f"/api/chat/sessions/{created['id']}",
        headers=chat_api.headers("other_student"),
    )

    assert owner.status_code == 200
    assert owner.json()["logs"][0]["referencedDocuments"] == referenced_documents
    assert owner.json()["logs"][0]["isGrounded"] is True
    assert other.status_code == 404


def test_owner_can_delete_session_and_logs(chat_api: ChatApiContext) -> None:
    created = create_session(chat_api)
    with chat_api.session_factory() as session:
        log = ChatLog(
            session_id=created["id"],
            user_id=chat_api.users["student"],
            course_id=chat_api.courses["owned"],
            question="질문",
            answer="답변",
            referenced_documents=[],
            model_name="test-model",
            response_time_ms=1,
            is_grounded=False,
            safety_result={},
            retrieval_result={},
        )
        session.add(log)
        session.commit()
        log_id = log.id

    denied = chat_api.client.delete(
        f"/api/chat/sessions/{created['id']}",
        headers=chat_api.headers("other_student"),
    )
    deleted = chat_api.client.delete(
        f"/api/chat/sessions/{created['id']}",
        headers=chat_api.headers("student"),
    )

    assert denied.status_code == 404
    assert deleted.status_code == 204
    with chat_api.session_factory() as session:
        assert session.get(ChatSession, created["id"]) is None
        assert session.get(ChatLog, log_id) is None
