"""Shared fixtures for the chat and log-review test suites."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.security import JWTService
from app.db.session import get_db
from app.main import app
from app.models import Base, Course, CourseAccess, User, UserRole

LECTURE_TEXT = """경사하강법은 손실 함수를 줄이기 위해 기울기의 반대 방향으로 파라미터를 갱신하는 최적화 방법이다.
학습률이 너무 크면 발산하고, 너무 작으면 수렴이 느려진다.

지도학습은 입력과 정답 레이블이 짝지어진 데이터로 모델을 학습시키는 방식이다.
분류와 회귀가 대표적인 지도학습 문제이다.

과적합은 모델이 학습 데이터에만 지나치게 맞춰져 새로운 데이터에서 성능이 떨어지는 현상이다.
정규화와 교차검증으로 과적합을 완화할 수 있다.
"""

OTHER_COURSE_TEXT = """소프트웨어공학에서 요구사항 분석은 이해관계자의 필요를 문서화하는 단계이다.
형상관리는 변경 이력을 추적하고 통제하는 활동이다.
"""


@dataclass(frozen=True)
class ChatApiContext:
    client: TestClient
    tokens: dict
    users: dict
    courses: dict
    session_factory: sessionmaker

    def headers(self, user_name: str) -> dict:
        return {"Authorization": f"Bearer {self.tokens[user_name]}"}

    def get(self, path: str, user_name: str):
        return self.client.get(path, headers=self.headers(user_name))

    def post(self, path: str, user_name: str, payload: dict):
        return self.client.post(path, headers=self.headers(user_name), json=payload)

    def upload(self, user_name: str, course_name: str, file_name: str, content: str):
        return self.client.post(
            f"/api/courses/{self.courses[course_name]}/materials",
            headers=self.headers(user_name),
            files={"file": (file_name, content.encode("utf-8"), "text/plain")},
        )

    def process(self, user_name: str, course_name: str, material_id: str, action: str = "process"):
        return self.client.post(
            f"/api/courses/{self.courses[course_name]}/materials/{material_id}/{action}",
            headers=self.headers(user_name),
        )

    def ask(self, user_name: str, course_name: str, question: str, **extra):
        payload = {"courseId": self.courses[course_name], "question": question}
        payload.update(extra)
        return self.post("/api/chat", user_name, payload)


def add_user(session: Session, email: str, role: UserRole) -> User:
    user = User(name=email, email=email, external_auth_id=f"external-{email}", role=role)
    session.add(user)
    session.flush()
    return user


def prepare_course_materials(chat_api: ChatApiContext) -> str:
    """Upload and process one material per course; returns the AI course material id."""

    ai_material = chat_api.upload("professor", "ai", "lecture1.txt", LECTURE_TEXT).json()
    se_material = chat_api.upload("other_professor", "se", "se-week1.txt", OTHER_COURSE_TEXT).json()

    assert chat_api.process("professor", "ai", ai_material["id"]).status_code == 200
    assert chat_api.process("other_professor", "se", se_material["id"]).status_code == 200
    return ai_material["id"]


@pytest.fixture
def chat_api(tmp_path: Path) -> Generator[ChatApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as session:
        users = {
            "admin": add_user(session, "chat-admin@skku.edu", UserRole.admin),
            "professor": add_user(session, "chat-professor@skku.edu", UserRole.professor),
            "other_professor": add_user(session, "chat-other-prof@skku.edu", UserRole.professor),
            "student": add_user(session, "chat-student@skku.edu", UserRole.student),
            "other_student": add_user(session, "chat-other-student@skku.edu", UserRole.student),
        }
        courses = {
            "ai": Course(
                name="인공지능개론",
                semester="2026-2",
                professor_id=users["professor"].id,
                is_active=True,
            ),
            "se": Course(
                name="소프트웨어공학",
                semester="2026-2",
                professor_id=users["other_professor"].id,
                is_active=True,
            ),
        }
        session.add_all(courses.values())
        session.flush()
        session.add_all(
            [
                CourseAccess(course_id=courses["ai"].id, user_id=users["student"].id),
                CourseAccess(course_id=courses["se"].id, user_id=users["other_student"].id),
            ]
        )
        session.commit()
        user_ids = {name: user.id for name, user in users.items()}
        course_ids = {name: course.id for name, course in courses.items()}

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    settings = Settings(
        upload_dir=str(tmp_path / "uploads"),
        use_mock_llm=True,
        chunk_size=200,
        chunk_overlap=40,
    )
    token_service = JWTService(
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expires_in,
    )
    tokens = {
        name: token_service.create_access_token(user_id) for name, user_id in user_ids.items()
    }

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield ChatApiContext(
            client=client,
            tokens=tokens,
            users=user_ids,
            courses=course_ids,
            session_factory=testing_session,
        )
    app.dependency_overrides.clear()
