"""A long PDF is indexed privately after upload and read by excerpt per question."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.api.routes import voice as voice_routes
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ChatLog
from app.services.voice import attachment_index, attachments, brain, external_brain, trusted_sites
from app.services.voice.session_store import get_context, reset_context
from test_voice_attachments import png_bytes, stream, text_pdf, upload

import pytest

MOCK_SETTINGS = Settings(_env_file=None, use_mock_llm=True)
FILLER = "This page discusses the general structure of the course and its schedule for the term."
SOFTMAX = (
    "Softmax normalizes a vector of scores into probabilities that sum to one. "
    "Softmax probabilities are used as attention weights over the values."
)
GRADIENT = (
    "Gradient descent updates the parameters in the direction opposite to the gradient "
    "of the loss so that the loss decreases step by step."
)


@pytest.fixture(autouse=True)
def isolated_voice_state(tmp_path, monkeypatch):
    monkeypatch.setattr(trusted_sites, "voice_storage_dir", lambda: tmp_path / "voice")
    monkeypatch.setattr(external_brain, "get_settings", lambda: MOCK_SETTINGS)
    monkeypatch.setattr(brain, "get_settings", lambda: MOCK_SETTINGS)


def textbook(pages: int = 12, softmax_page: int = 5, gradient_page: int = 9) -> bytes:
    """A PDF long enough to be indexed, with two pages about distinct topics."""
    content = []
    for number in range(1, pages + 1):
        if number == softmax_page:
            content.append([SOFTMAX[:90], SOFTMAX[90:]])
        elif number == gradient_page:
            content.append([GRADIENT[:80], GRADIENT[80:]])
        else:
            content.append([FILLER, f"Page {number} of the textbook."])
    return text_pdf(content)


def settings_for(tmp_path, **overrides) -> Settings:
    values = {
        "upload_dir": str(tmp_path / "uploads"), "use_mock_llm": True,
        "embedding_provider": "mock", "attachment_inline_max_pages": 8, "chunk_size": 200,
        "chunk_overlap": 40,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def store(settings, name: str, data: bytes) -> attachments.Attachment:
    return attachments.store_attachment(
        data, filename=name, user_id="student-1", course_id="course-1", settings=settings
    )


# --------------------------------------------------------------------------
# The index itself
# --------------------------------------------------------------------------


def test_a_long_pdf_is_indexed_and_searched_by_page(tmp_path) -> None:
    settings = settings_for(tmp_path)
    book = store(settings, "textbook.pdf", textbook())
    assert attachment_index.needs_index(book, settings)
    assert not attachment_index.needs_index(store(settings, "short.pdf", text_pdf([[FILLER]])), settings)
    assert attachment_index.index_status(book) is None

    attachment_index.mark_indexing(book)
    assert attachment_index.index_status(book)["status"] == "indexing"
    attachment_index.build_index(book, settings)

    status = attachment_index.index_status(book)
    assert status["status"] == "ready"
    assert status["pages"] == 12 and status["pages_done"] == 12 and status["chunks"] >= 12
    index = json.loads(attachment_index.index_path(book).read_text(encoding="utf-8"))
    assert index["pages_with_text"] == 12
    assert all(len(chunk["embedding"]) > 0 for chunk in index["chunks"])

    hits = attachment_index.search_index(book, "softmax probabilities", settings, top_k=2)
    assert hits and hits[0].page == 5 and "Softmax" in hits[0].text
    hits = attachment_index.search_index(book, "gradient descent loss", settings, top_k=1)
    assert [hit.page for hit in hits] == [9]
    # No question yet: the opening of the book, in page order.
    opening = attachment_index.search_index(book, "", settings, top_k=3)
    assert [hit.page for hit in opening] == [1, 1, 2] or opening[0].page == 1


def test_reading_an_indexed_pdf_pulls_only_the_matching_pages(tmp_path) -> None:
    # The mock embedding is a bag of words, so pages that share no word with the
    # question tie near zero; one excerpt keeps the check about the match itself.
    settings = settings_for(tmp_path, attachment_index_top_k=1)
    book = store(settings, "textbook.pdf", textbook())
    attachment_index.build_index(book, settings)

    [content] = attachments.read_attachments(
        [book], settings=settings, llm=None, query="softmax probabilities attention"
    )

    assert content.mode == "excerpt" and content.pages == 12
    assert 5 in content.pages_used and content.text.startswith("[")
    assert "Softmax normalizes" in content.text
    assert "Page 3 of the textbook" not in content.text
    assert content.error is None
    block = attachments.model_content("소프트맥스가 뭐야?", [content])
    assert "### textbook.pdf (PDF 12쪽 중 질문과 관련된" in block
    label, detail = attachments.read_label([content])
    assert label == "첨부 파일에서 관련 쪽을 찾았어요"
    assert detail.startswith("textbook.pdf ") and detail.endswith("쪽 참고")
    # The log round trip keeps the mode and the pages used.
    restored = attachments.from_logged(attachments.logged_list([content]))[0]
    assert restored.mode == "excerpt" and restored.pages_used == content.pages_used


def test_an_unindexed_or_failed_pdf_reads_as_an_error_not_a_crash(tmp_path) -> None:
    settings = settings_for(tmp_path)
    book = store(settings, "textbook.pdf", textbook())

    [pending] = attachments.read_attachments([book], settings=settings, llm=None, query="x")
    assert pending.text == "" and "색인이 아직" in pending.error

    attachment_index.mark_indexing(book)
    attachment_index._write_status(book, status="failed", message="색인용 임베딩 서버를 사용할 수 없어요")
    [failed] = attachments.read_attachments([book], settings=settings, llm=None, query="x")
    assert failed.error == "색인용 임베딩 서버를 사용할 수 없어요"


def test_a_scanned_book_fails_indexing_with_a_reason(tmp_path) -> None:
    settings = settings_for(tmp_path)
    scan = store(settings, "scan.pdf", text_pdf([[] for _ in range(10)]))
    attachment_index.build_index(scan, settings)
    status = attachment_index.index_status(scan)
    assert status["status"] == "failed" and "스캔본" in status["message"]


def test_index_files_do_not_count_as_stored_files_and_go_with_their_file(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_max_stored_files=2)
    book = store(settings, "textbook.pdf", textbook())
    attachment_index.mark_indexing(book)
    attachment_index.build_index(book, settings)
    directory = Path(book.path).parent
    assert len(list(directory.glob("*"))) == 4  # pdf, sidecar, status, index

    store(settings, "a.png", png_bytes())
    store(settings, "b.png", png_bytes())  # two files max: the book is the oldest and goes
    remaining = sorted(path.name for path in directory.glob("*"))
    assert not any(name.startswith(book.id) for name in remaining)
    assert len(remaining) == 4  # two images, two sidecars

    loaded = attachments.load_attachment(
        book.id, user_id="student-1", course_id="course-1", settings=settings
    )
    assert loaded is None


def test_attachment_query_is_the_question_unless_it_cannot_stand_alone() -> None:
    from unittest.mock import AsyncMock

    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", AsyncMock())
    context.append_history({"role": "user", "content": "소프트맥스가 뭐야?\n\n" + attachments.ATTACHMENT_HEADER + "\n### 교재.pdf\n본문"})
    context.append_history({"role": "assistant", "content": "이름부터 볼게요. 맥스는 무엇을 고를까요?"})

    # Names its topic: searched as is, without the tutor's reply.
    assert brain.attachment_query(context, "gradient descent loss는 어떻게 줄어?") == (
        "gradient descent loss는 어떻게 줄어?"
    )
    # Too short to stand alone: the previous question comes along, its file block not.
    assert brain.attachment_query(context, "그럼 2번은?") == "소프트맥스가 뭐야?\n그럼 2번은?"
    assert brain.attachment_query(
        brain.VoiceContext("c", "n", "u", AsyncMock()), "왜?"
    ) == "왜?"


# --------------------------------------------------------------------------
# Through the API
# --------------------------------------------------------------------------


def test_uploading_a_textbook_indexes_it_and_questions_read_the_matching_pages(
    chat_api, monkeypatch
) -> None:
    course_id = chat_api.courses["ai"]
    student_id = chat_api.users["student"]
    reset_context(student_id, course_id)
    monkeypatch.setattr(voice_routes, "SessionLocal", chat_api.session_factory)
    settings = app.dependency_overrides[get_settings]()
    monkeypatch.setattr(settings, "attachment_inline_max_pages", 8)
    monkeypatch.setattr(settings, "attachment_index_top_k", 1)
    monkeypatch.setattr(settings, "chunk_size", 200)
    monkeypatch.setattr(settings, "chunk_overlap", 40)
    queries: list[str] = []

    def search(_course_id, query):
        queries.append(query)
        return json.dumps({"found": False}), []

    monkeypatch.setattr(brain, "search_course_materials", search)

    uploaded = upload(chat_api, "student", "ai", "교재.pdf", textbook(), "application/pdf")
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["mode"] == "excerpt" and body["pages"] == 12
    assert body["index"]["status"] == "indexing"

    # The TestClient runs the background task before returning; the status shows it.
    status = chat_api.get(
        f"/api/voice/courses/{course_id}/attachments/{body['id']}", "student"
    ).json()
    assert status["index"]["status"] == "ready" and status["index"]["pages_done"] == 12
    denied = chat_api.get(
        f"/api/voice/courses/{course_id}/attachments/{body['id']}", "other_student"
    )
    assert denied.status_code == 403

    events = stream(
        chat_api, "student", "ai",
        {"text": "소프트맥스가 뭐야? softmax probabilities", "attachment_ids": [body["id"]]},
    )
    done = events[-1]
    assert done["attachments"][0]["mode"] == "excerpt"
    assert 5 in done["attachments"][0]["pages_used"]
    final = {e["key"]: e for e in events if e["type"] == "step"}
    assert final["attachments"]["label"] == "첨부 파일에서 관련 쪽을 찾았어요"
    assert final["attachments"]["detail"].startswith("교재.pdf ")
    history = get_context(student_id, course_id, "인공지능개론").history
    assert "[5쪽]" in history[0]["content"] and "Softmax normalizes" in history[0]["content"]
    assert "Page 3 of the textbook" not in history[0]["content"]
    with chat_api.session_factory() as session:
        log = session.scalar(select(ChatLog).where(ChatLog.id == done["log_id"]))
        assert log.retrieval_result["attachments"][0]["mode"] == "excerpt"

    # A second question about another topic pulls other pages of the same book.
    events = stream(
        chat_api, "student", "ai",
        {"text": "gradient descent loss는 어떻게 줄어?", "attachment_ids": [body["id"]]},
    )
    assert 9 in events[-1]["attachments"][0]["pages_used"]


def test_a_question_waits_for_the_index(chat_api, monkeypatch) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)
    settings = app.dependency_overrides[get_settings]()
    monkeypatch.setattr(settings, "attachment_inline_max_pages", 8)
    # Keep the background task from finishing the index, as on a real server.
    monkeypatch.setattr(voice_routes.attachment_index, "build_index", lambda *_: None)

    body = upload(chat_api, "student", "ai", "교재.pdf", textbook(), "application/pdf").json()
    assert body["index"]["status"] == "indexing"

    waiting = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text", "student",
        {"text": "소프트맥스가 뭐야?", "attachment_ids": [body["id"]]},
    )
    assert waiting.status_code == 409
    assert "색인이 아직" in waiting.json()["detail"]

    attachment = attachments.load_attachment(
        body["id"], user_id=chat_api.users["student"], course_id=course_id, settings=settings
    )
    attachment_index._write_status(attachment, status="failed", message="파일을 색인하지 못했어요")
    failed = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text", "student",
        {"text": "소프트맥스가 뭐야?", "attachment_ids": [body["id"]]},
    )
    assert failed.status_code == 422 and "색인하지 못했어요" in failed.json()["detail"]
