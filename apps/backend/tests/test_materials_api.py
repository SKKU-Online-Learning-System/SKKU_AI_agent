from __future__ import annotations

import asyncio
from collections.abc import Generator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import get_ident
from uuid import UUID

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import materials as materials_routes
from app.core.config import Settings, get_settings
from app.core.security import JWTService
from app.db.session import get_db
from app.main import app
from app.models import Base, Course, CourseAccess, CourseMaterial, CourseMaterialStatus, User, UserRole
from app.services.material_service import save_upload


@dataclass(frozen=True)
class MaterialApiContext:
    client: TestClient
    tokens: dict[str, str]
    users: dict[str, str]
    courses: dict[str, str]
    session_factory: sessionmaker[Session]
    upload_dir: Path

    def headers(self, user_name: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens[user_name]}"}

    def upload(self, user_name: str, course_name: str, file_name: str, content: bytes):
        return self.client.post(
            f"/api/courses/{self.courses[course_name]}/materials",
            headers=self.headers(user_name),
            files={"file": (file_name, content, "application/octet-stream")},
        )


def add_user(session: Session, email: str, role: UserRole) -> User:
    user = User(
        name=email,
        email=email,
        external_auth_id=f"external-{email}",
        role=role,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def material_api(tmp_path: Path) -> Generator[MaterialApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as session:
        users = {
            "admin": add_user(session, "materials-admin@skku.edu", UserRole.admin),
            "professor": add_user(session, "materials-professor@skku.edu", UserRole.professor),
            "other_professor": add_user(
                session,
                "materials-other-professor@skku.edu",
                UserRole.professor,
            ),
            "student": add_user(session, "materials-student@skku.edu", UserRole.student),
        }
        courses = {
            "owned": Course(
                name="Owned Materials Course",
                semester="2026-2",
                professor_id=users["professor"].id,
                is_active=True,
            ),
            "other": Course(
                name="Other Materials Course",
                semester="2026-2",
                professor_id=users["other_professor"].id,
                is_active=True,
            ),
        }
        session.add_all(courses.values())
        session.flush()
        session.add(CourseAccess(course_id=courses["owned"].id, user_id=users["student"].id))
        session.commit()
        user_ids = {name: user.id for name, user in users.items()}
        course_ids = {name: course.id for name, course in courses.items()}

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    upload_dir = tmp_path / "uploads"
    settings = Settings(upload_dir=str(upload_dir), max_upload_size_bytes=4)
    token_service = JWTService(
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expires_in,
    )
    tokens = {
        name: token_service.create_access_token(user_id)
        for name, user_id in user_ids.items()
    }

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield MaterialApiContext(
            client=client,
            tokens=tokens,
            users=user_ids,
            courses=course_ids,
            session_factory=testing_session,
            upload_dir=upload_dir,
        )
    app.dependency_overrides.clear()


def test_professor_uploads_lists_and_deletes_material(material_api: MaterialApiContext) -> None:
    uploaded = material_api.upload("professor", "owned", "week1.txt", b"note")

    assert uploaded.status_code == 202
    body = uploaded.json()
    assert body["courseId"] == material_api.courses["owned"]
    assert body["originalFileName"] == "week1.txt"
    assert body["fileType"] == "txt"
    assert body["fileSize"] == 4
    assert body["processingStatus"] == "pending"

    listed = material_api.client.get(
        f"/api/courses/{material_api.courses['owned']}/materials",
        headers=material_api.headers("professor"),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]

    deleted = material_api.client.delete(
        f"/api/courses/{material_api.courses['owned']}/materials/{body['id']}",
        headers=material_api.headers("professor"),
    )
    assert deleted.status_code == 204
    assert [path for path in material_api.upload_dir.rglob("*") if path.is_file()] == []
    with material_api.session_factory() as session:
        assert session.get(CourseMaterial, body["id"]) is None


@pytest.mark.parametrize(
    ("file_name", "content", "expected_detail"),
    [
        ("malware.exe", b"x", "Allowed file types: .pdf, .pptx, .docx, .txt"),
        ("empty.txt", b"", "Uploaded file must not be empty"),
        ("large.txt", b"12345", "Uploaded file exceeds the 4 byte limit"),
    ],
)
def test_upload_validation_rejects_invalid_files(
    material_api: MaterialApiContext,
    file_name: str,
    content: bytes,
    expected_detail: str,
) -> None:
    response = material_api.upload("professor", "owned", file_name, content)

    assert response.status_code == 422
    assert response.json() == {"detail": expected_detail}
    assert [path for path in material_api.upload_dir.rglob("*") if path.is_file()] == []
    with material_api.session_factory() as session:
        assert session.scalars(select(CourseMaterial)).all() == []


def test_other_professor_cannot_list_upload_or_delete_owned_material(
    material_api: MaterialApiContext,
) -> None:
    material = material_api.upload("professor", "owned", "week1.txt", b"note").json()
    course_url = f"/api/courses/{material_api.courses['owned']}/materials"

    listed = material_api.client.get(course_url, headers=material_api.headers("other_professor"))
    uploaded = material_api.upload("other_professor", "owned", "week2.txt", b"note")
    deleted = material_api.client.delete(
        f"{course_url}/{material['id']}",
        headers=material_api.headers("other_professor"),
    )

    assert listed.status_code == 403
    assert uploaded.status_code == 403
    assert deleted.status_code == 403


def test_student_can_list_accessible_course_but_cannot_upload_or_delete(
    material_api: MaterialApiContext,
) -> None:
    material = material_api.upload("professor", "owned", "week1.txt", b"note").json()
    course_url = f"/api/courses/{material_api.courses['owned']}/materials"

    listed = material_api.client.get(course_url, headers=material_api.headers("student"))
    uploaded = material_api.upload("student", "owned", "week2.txt", b"note")
    deleted = material_api.client.delete(
        f"{course_url}/{material['id']}",
        headers=material_api.headers("student"),
    )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [material["id"]]
    assert uploaded.status_code == 403
    assert deleted.status_code == 403


def test_delete_material_from_another_course_returns_not_found(
    material_api: MaterialApiContext,
) -> None:
    with material_api.session_factory() as session:
        other_material = CourseMaterial(
            course_id=material_api.courses["other"],
            uploaded_by=material_api.users["other_professor"],
            file_name="other.txt",
            original_file_name="other.txt",
            file_type="txt",
            file_size=4,
            storage_path=str(material_api.upload_dir / "other.txt"),
            processing_status=CourseMaterialStatus.pending,
        )
        session.add(other_material)
        session.commit()
        other_material_id = other_material.id

    response = material_api.client.delete(
        f"/api/courses/{material_api.courses['owned']}/materials/{other_material_id}",
        headers=material_api.headers("professor"),
    )

    assert response.status_code == 404


def test_uploaded_file_uses_uuid_internal_name_and_preserves_original_name(
    material_api: MaterialApiContext,
) -> None:
    response = material_api.upload("professor", "owned", "lecture-notes.txt", b"note")

    assert response.status_code == 202
    with material_api.session_factory() as session:
        material = session.get(CourseMaterial, response.json()["id"])
        assert material is not None
        assert material.original_file_name == "lecture-notes.txt"
        assert material.file_name != material.original_file_name
        UUID(Path(material.file_name).stem)
        assert Path(material.storage_path).is_file()


def test_failed_database_insert_leaves_no_record_or_file(
    material_api: MaterialApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_commit(self: Session) -> None:
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(Session, "commit", fail_commit)

    response = material_api.upload("professor", "owned", "week1.txt", b"note")

    assert response.status_code == 500
    assert [path for path in material_api.upload_dir.rglob("*") if path.is_file()] == []
    with material_api.session_factory() as session:
        assert session.scalars(select(CourseMaterial)).all() == []


def test_failed_database_refresh_rolls_back_record_and_removes_file(
    material_api: MaterialApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_refresh(self: Session, instance: object) -> None:
        raise SQLAlchemyError("refresh unavailable")

    monkeypatch.setattr(Session, "refresh", fail_refresh)

    response = material_api.upload("professor", "owned", "week1.txt", b"note")

    assert response.status_code == 500
    assert [path for path in material_api.upload_dir.rglob("*") if path.is_file()] == []
    with material_api.session_factory() as session:
        assert session.scalars(select(CourseMaterial)).all() == []


def test_delete_succeeds_when_stored_file_is_already_missing(
    material_api: MaterialApiContext,
) -> None:
    missing_path = material_api.upload_dir / "already-missing.txt"
    with material_api.session_factory() as session:
        material = CourseMaterial(
            course_id=material_api.courses["owned"],
            uploaded_by=material_api.users["professor"],
            file_name=missing_path.name,
            original_file_name="already-missing.txt",
            file_type="txt",
            file_size=4,
            storage_path=str(missing_path),
            processing_status=CourseMaterialStatus.pending,
        )
        session.add(material)
        session.commit()
        material_id = material.id

    response = material_api.client.delete(
        f"/api/courses/{material_api.courses['owned']}/materials/{material_id}",
        headers=material_api.headers("professor"),
    )

    assert response.status_code == 204
    assert response.content == b""
    with material_api.session_factory() as session:
        assert session.get(CourseMaterial, material_id) is None


def test_delete_keeps_committed_204_and_logs_post_commit_unlink_failure(
    material_api: MaterialApiContext,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    uploaded = material_api.upload("professor", "owned", "week1.txt", b"note").json()
    with material_api.session_factory() as session:
        material = session.get(CourseMaterial, uploaded["id"])
        assert material is not None
        storage_path = material.storage_path

    def fail_unlink(path: str | Path) -> None:
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(materials_routes, "remove_stored_file", fail_unlink)

    response = material_api.client.delete(
        f"/api/courses/{material_api.courses['owned']}/materials/{uploaded['id']}",
        headers=material_api.headers("professor"),
    )

    assert response.status_code == 204
    assert response.content == b""
    assert uploaded["id"] in caplog.text
    assert storage_path in caplog.text
    assert storage_path not in response.text
    with material_api.session_factory() as session:
        assert session.get(CourseMaterial, uploaded["id"]) is None


def test_save_upload_writes_destination_off_the_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_loop_thread = get_ident()
    write_threads: list[int] = []

    class RecordingDestination:
        def __enter__(self) -> "RecordingDestination":
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

        def write(self, chunk: bytes) -> int:
            write_threads.append(get_ident())
            return len(chunk)

        def close(self) -> None:
            return None

    destination = RecordingDestination()

    def open_destination(self: Path, mode: str) -> RecordingDestination:
        assert mode == "wb"
        return destination

    monkeypatch.setattr(Path, "open", open_destination)
    upload = UploadFile(file=BytesIO(b"note"), filename="week1.txt")

    asyncio.run(save_upload(upload, "course-1", tmp_path, max_size_bytes=4))

    assert write_threads
    assert all(thread_id != event_loop_thread for thread_id in write_threads)
