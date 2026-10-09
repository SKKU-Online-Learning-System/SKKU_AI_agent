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
from app.services.material_service import save_upload
from app.services.material_processing_service import (
    MaterialProcessingService,
)
from app.services.document_parser_service import ParsedDocument, ParsedPage


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

    def upload(
        self,
        user_name: str,
        course_name: str,
        file_name: str,
        content: bytes,
        week: int = 1,
    ):
        return self.client.post(
            f"/api/courses/{self.courses[course_name]}/materials",
            headers=self.headers(user_name),
            data={"week": str(week)},
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
def material_api(tmp_path: Path, monkeypatch) -> Generator[MaterialApiContext, None, None]:
    # These cases drive /process explicitly; automatic upload work is tested separately.
    monkeypatch.setattr(
        "app.api.routes.materials.process_uploaded_material", lambda *args: None,
    )
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
    settings = Settings(
        embedding_provider="mock",
        rag_text_score_threshold=0.1,
        rag_score_threshold=0.1,
        upload_dir=str(upload_dir), max_upload_size_bytes=4, mock_embedding_dim=128
    )
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
    uploaded = material_api.upload("professor", "owned", "week3.txt", b"note", week=3)

    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["courseId"] == material_api.courses["owned"]
    assert body["originalFileName"] == "week3.txt"
    assert body["fileType"] == "txt"
    assert body["fileSize"] == 4
    assert body["week"] == 3
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


def test_student_can_download_professor_material(material_api: MaterialApiContext) -> None:
    material = material_api.upload(
        "professor", "owned", "week4.txt", b"link", week=4
    ).json()

    downloaded = material_api.client.get(
        f"/api/courses/{material_api.courses['owned']}/materials/{material['id']}/download",
        headers=material_api.headers("student"),
    )

    assert downloaded.status_code == 200
    assert downloaded.content == b"link"
    assert "week4.txt" in downloaded.headers["content-disposition"]


@pytest.mark.parametrize("week", [0, 17])
def test_upload_rejects_week_outside_semester_range(
    material_api: MaterialApiContext,
    week: int,
) -> None:
    response = material_api.upload(
        "professor", "owned", "invalid-week.txt", b"note", week=week
    )

    assert response.status_code == 422
    assert [path for path in material_api.upload_dir.rglob("*") if path.is_file()] == []


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

    assert response.status_code == 201
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


def test_professor_processes_and_reprocesses_pending_material(
    material_api: MaterialApiContext,
) -> None:
    uploaded = material_api.upload(
        "professor",
        "owned",
        "lecture.txt",
        b"note",
    ).json()
    base_url = (
        f"/api/courses/{material_api.courses['owned']}/materials/{uploaded['id']}"
    )

    pending = material_api.client.get(
        f"{base_url}/processing-status",
        headers=material_api.headers("professor"),
    )
    processed = material_api.client.post(
        f"{base_url}/process",
        headers=material_api.headers("professor"),
    )

    assert pending.status_code == 200
    assert pending.json()["processingStatus"] == "pending"
    assert pending.json()["chunkCount"] == 0
    assert processed.status_code == 200
    assert processed.json()["processingStatus"] == "completed"
    assert processed.json()["processingError"] is None
    assert processed.json()["chunkCount"] == 1

    with material_api.session_factory() as session:
        first_chunk = session.scalar(
            select(DocumentChunk).where(DocumentChunk.material_id == uploaded["id"])
        )
        assert first_chunk is not None
        first_chunk_id = first_chunk.id
        assert first_chunk.chunk_text == "note"
        first_embedding = first_chunk.embedding
        assert first_embedding is not None
        assert len(first_embedding) == 128
        assert first_chunk.embedding_model == "mock-hash-128"

    duplicate = material_api.client.post(
        f"{base_url}/process",
        headers=material_api.headers("professor"),
    )
    reprocessed = material_api.client.post(
        f"{base_url}/reprocess",
        headers=material_api.headers("professor"),
    )

    assert duplicate.status_code == 409
    assert reprocessed.status_code == 200
    assert reprocessed.json()["processingStatus"] == "completed"
    assert reprocessed.json()["chunkCount"] == 1
    with material_api.session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.material_id == uploaded["id"])
        ).all()
        assert len(chunks) == 1
        assert chunks[0].id != first_chunk_id
        assert chunks[0].embedding == first_embedding


def test_processing_failure_is_persisted_and_can_be_retried(
    material_api: MaterialApiContext,
) -> None:
    uploaded = material_api.upload(
        "professor",
        "owned",
        "missing.txt",
        b"note",
    ).json()
    with material_api.session_factory() as session:
        material = session.get(CourseMaterial, uploaded["id"])
        assert material is not None
        Path(material.storage_path).unlink()

    base_url = (
        f"/api/courses/{material_api.courses['owned']}/materials/{uploaded['id']}"
    )
    failed = material_api.client.post(
        f"{base_url}/process",
        headers=material_api.headers("professor"),
    )
    status_response = material_api.client.get(
        f"{base_url}/processing-status",
        headers=material_api.headers("professor"),
    )
    retried = material_api.client.post(
        f"{base_url}/reprocess",
        headers=material_api.headers("professor"),
    )

    assert failed.status_code == 422
    assert failed.json() == {
        "detail": "MATERIAL_FILE_NOT_FOUND: 자료 파일을 찾을 수 없습니다."
    }
    assert status_response.status_code == 200
    assert status_response.json()["processingStatus"] == "failed"
    assert status_response.json()["processingError"] == (
        "MATERIAL_FILE_NOT_FOUND: 자료 파일을 찾을 수 없습니다."
    )
    assert status_response.json()["chunkCount"] == 0
    assert retried.status_code == 422
    assert retried.json() == {
        "detail": "MATERIAL_FILE_NOT_FOUND: 자료 파일을 찾을 수 없습니다."
    }


def test_processing_endpoints_enforce_manage_permission_and_course_scope(
    material_api: MaterialApiContext,
) -> None:
    owned = material_api.upload(
        "professor",
        "owned",
        "owned.txt",
        b"note",
    ).json()
    owned_base_url = (
        f"/api/courses/{material_api.courses['owned']}/materials/{owned['id']}"
    )

    for suffix, method in [
        ("process", material_api.client.post),
        ("reprocess", material_api.client.post),
        ("processing-status", material_api.client.get),
    ]:
        assert method(
            f"{owned_base_url}/{suffix}",
            headers=material_api.headers("student"),
        ).status_code == 403
        assert method(
            f"{owned_base_url}/{suffix}",
            headers=material_api.headers("other_professor"),
        ).status_code == 403

    admin_processed = material_api.client.post(
        f"{owned_base_url}/process",
        headers=material_api.headers("admin"),
    )
    assert admin_processed.status_code == 200

    other = material_api.upload(
        "other_professor",
        "other",
        "other.txt",
        b"note",
    ).json()
    wrong_course = material_api.client.post(
        f"/api/courses/{material_api.courses['owned']}/materials/{other['id']}/process",
        headers=material_api.headers("admin"),
    )
    assert wrong_course.status_code == 404


def test_processing_claim_is_visible_and_rejects_concurrent_request(
    material_api: MaterialApiContext,
) -> None:
    uploaded = material_api.upload(
        "professor",
        "owned",
        "claim.txt",
        b"note",
    ).json()
    observed_statuses: list[CourseMaterialStatus] = []

    class ObservingParser:
        def parse(self, material: CourseMaterial) -> ParsedDocument:
            with material_api.session_factory() as observation_session:
                observed = observation_session.get(CourseMaterial, material.id)
                assert observed is not None
                observed_statuses.append(observed.processing_status)
            return ParsedDocument(
                material_id=material.id,
                course_id=material.course_id,
                title=material.original_file_name,
                pages=(ParsedPage(page_number=None, text="placeholder"),),
                full_text="placeholder",
            )

    with material_api.session_factory() as session:
        result = MaterialProcessingService(
            session,
            settings=Settings(embedding_provider="mock"),
            parser=ObservingParser(),
        ).process_material(material_api.courses["owned"], uploaded["id"])

    assert observed_statuses == [CourseMaterialStatus.processing]
    assert result.processing_status == CourseMaterialStatus.completed

    with material_api.session_factory() as session:
        material = session.get(CourseMaterial, uploaded["id"])
        assert material is not None
        material.processing_status = CourseMaterialStatus.processing
        session.commit()

    conflict = material_api.client.post(
        (
            f"/api/courses/{material_api.courses['owned']}/materials/"
            f"{uploaded['id']}/reprocess"
        ),
        headers=material_api.headers("professor"),
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    ("file_type", "content", "expected_error"),
    [
        ("txt", b"", "DOCUMENT_TEXT_NOT_FOUND"),
        ("hwp", b"hwp", "DOCUMENT_UNSUPPORTED_TYPE"),
    ],
)
def test_parser_failure_marks_material_failed(
    material_api: MaterialApiContext,
    file_type: str,
    content: bytes,
    expected_error: str,
) -> None:
    path = material_api.upload_dir / f"manual.{file_type}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with material_api.session_factory() as session:
        material = CourseMaterial(
            course_id=material_api.courses["owned"],
            uploaded_by=material_api.users["professor"],
            file_name=path.name,
            original_file_name=path.name,
            file_type=file_type,
            file_size=len(content),
            storage_path=str(path),
            processing_status=CourseMaterialStatus.pending,
        )
        session.add(material)
        session.commit()
        material_id = material.id

    response = material_api.client.post(
        (
            f"/api/courses/{material_api.courses['owned']}/materials/"
            f"{material_id}/process"
        ),
        headers=material_api.headers("professor"),
    )

    assert response.status_code == 422
    assert expected_error in response.json()["detail"]
    with material_api.session_factory() as session:
        failed = session.get(CourseMaterial, material_id)
        assert failed is not None
        assert failed.processing_status == CourseMaterialStatus.failed
        assert failed.processing_error is not None
        assert expected_error in failed.processing_error


def test_process_splits_long_text_and_reprocess_replaces_chunks(
    material_api: MaterialApiContext,
) -> None:
    path = material_api.upload_dir / "long-lecture.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("가" * 2200, encoding="utf-8")
    with material_api.session_factory() as session:
        material = CourseMaterial(
            course_id=material_api.courses["owned"],
            uploaded_by=material_api.users["professor"],
            file_name=path.name,
            original_file_name=path.name,
            file_type="txt",
            file_size=path.stat().st_size,
            storage_path=str(path),
            processing_status=CourseMaterialStatus.pending,
        )
        session.add(material)
        session.commit()
        material_id = material.id

    base_url = (
        f"/api/courses/{material_api.courses['owned']}/materials/{material_id}"
    )
    processed = material_api.client.post(
        f"{base_url}/process",
        headers=material_api.headers("professor"),
    )

    assert processed.status_code == 200
    assert processed.json()["chunkCount"] == 3
    with material_api.session_factory() as session:
        first_chunks = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.material_id == material_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
        first_ids = {chunk.id for chunk in first_chunks}
        assert [chunk.chunk_index for chunk in first_chunks] == [0, 1, 2]
        assert [chunk.page_number for chunk in first_chunks] == [1, 1, 1]
        assert [chunk.char_count for chunk in first_chunks] == [1000, 1000, 500]
        assert all(chunk.course_id == material_api.courses["owned"] for chunk in first_chunks)

    reprocessed = material_api.client.post(
        f"{base_url}/reprocess",
        headers=material_api.headers("professor"),
    )

    assert reprocessed.status_code == 200
    assert reprocessed.json()["chunkCount"] == 3
    with material_api.session_factory() as session:
        replacement_chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.material_id == material_id)
        ).all()
        assert len(replacement_chunks) == 3
        assert first_ids.isdisjoint(chunk.id for chunk in replacement_chunks)
