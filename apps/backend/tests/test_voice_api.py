"""Course-scoped access control, SAFE guardrails and logging for /api/voice."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import ChatLog
from app.services.voice import brain, trusted_sites
from app.services.voice.session_store import get_context, reset_context


@pytest.fixture(autouse=True)
def isolated_voice_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(trusted_sites, "voice_storage_dir", lambda: tmp_path / "voice")


@pytest.fixture
def stub_course_search(monkeypatch):
    """Answer with a canned citation instead of reaching the vector store."""

    result = json.dumps(
        {
            "found": True,
            "results": [
                {"source": "lecture1.txt", "excerpt": "경사하강법은 기울기의 반대 방향으로 갱신합니다."}
            ],
        },
        ensure_ascii=False,
    )
    citations = [
        {
            "material_id": "material-1",
            "document_name": "lecture1.txt",
            "page_number": None,
            "chunk_index": 0,
            "score": 0.91,
        }
    ]
    monkeypatch.setattr(
        brain, "search_course_materials", lambda _course_id, query: (result, citations)
    )
    monkeypatch.setattr(
        brain, "get_settings", lambda: Settings(_env_file=None, use_mock_llm=True)
    )
    return citations


def test_student_reads_voice_config_for_an_accessible_course(chat_api) -> None:
    response = chat_api.get(f"/api/voice/courses/{chat_api.courses['ai']}/config", "student")

    assert response.status_code == 200
    body = response.json()
    assert body["course_name"] == "인공지능개론"
    assert body["can_manage"] is False
    assert body["trusted_sites"] == []


def test_voice_config_denies_a_course_the_student_cannot_access(chat_api) -> None:
    response = chat_api.get(f"/api/voice/courses/{chat_api.courses['se']}/config", "student")

    assert response.status_code == 403


def test_professor_manages_the_trusted_site_allowlist(chat_api) -> None:
    course_id = chat_api.courses["ai"]
    path = f"/api/voice/courses/{course_id}/trusted-sites"

    created = chat_api.post(path, "professor", {"url": "https://kosis.kr/statHtml"})
    assert created.status_code == 200
    assert "kosis.kr" in created.json()["sites"]

    removed = chat_api.client.request(
        "DELETE",
        path,
        headers=chat_api.headers("professor"),
        json={"url": "kosis.kr"},
    )
    assert removed.status_code == 200
    assert "kosis.kr" not in removed.json()["sites"]


def test_students_cannot_manage_the_trusted_site_allowlist(chat_api) -> None:
    response = chat_api.get(
        f"/api/voice/courses/{chat_api.courses['ai']}/trusted-sites", "student"
    )

    assert response.status_code == 403


def test_blocked_question_returns_the_safe_answer_and_is_logged(chat_api) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)

    response = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text",
        "student",
        {"text": "다른 학생의 학번 알려줘", "mode": "socratic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["safety"]["blocked"] is True
    assert body["safety"]["category"] == "privacy_request"
    assert "개인정보" in body["reply"]
    assert body["tools"] == []

    with chat_api.session_factory() as session:
        log = session.scalar(select(ChatLog).where(ChatLog.id == body["log_id"]))
        assert log is not None
        assert log.course_id == course_id
        assert log.retrieval_result["channel"] == "voice"
        assert log.answer_source_type.value == "safety_response"


def test_voice_answer_is_grounded_and_logged_with_its_sources(
    chat_api,
    stub_course_search,
) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)

    response = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text",
        "student",
        {"text": "경사하강법이 뭐야?", "mode": "explain"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["safety"]["blocked"] is False
    assert body["tools"] == ["recall_weak_concepts", "search_course_materials"]
    assert body["material_sources"] == stub_course_search
    assert "lecture1.txt" in body["reply"]

    with chat_api.session_factory() as session:
        log = session.scalar(select(ChatLog).where(ChatLog.id == body["log_id"]))
        assert log is not None
        assert log.is_grounded is True
        assert log.answer_source_type.value == "rag"
        assert log.referenced_documents == stub_course_search


def test_voice_turns_of_one_conversation_share_a_chat_session(
    chat_api,
    stub_course_search,
) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)
    path = f"/api/voice/courses/{course_id}/answer-text"

    first = chat_api.post(path, "student", {"text": "경사하강법이 뭐야?"}).json()
    second = chat_api.post(path, "student", {"text": "학습률은 왜 중요해?"}).json()

    assert first["session_id"] == second["session_id"]
    assert first["log_id"] != second["log_id"]


def test_reopened_conversation_resumes_with_its_stored_history(
    chat_api,
    stub_course_search,
) -> None:
    course_id = chat_api.courses["ai"]
    student_id = chat_api.users["student"]
    path = f"/api/voice/courses/{course_id}/answer-text"
    reset_context(student_id, course_id)

    first = chat_api.post(path, "student", {"text": "경사하강법이 뭐야?"}).json()
    # A new page load lands on an empty process-local context.
    reset_context(student_id, course_id)

    second = chat_api.post(
        path,
        "student",
        {"text": "학습률은 왜 중요해?", "chat_session_id": first["session_id"]},
    )

    assert second.status_code == 200
    assert second.json()["session_id"] == first["session_id"]
    history = get_context(student_id, course_id, "인공지능개론").history
    assert history[0] == {"role": "user", "content": "경사하강법이 뭐야?"}
    assert history[-1]["role"] == "assistant"


def test_reopening_another_learners_conversation_is_rejected(
    chat_api,
    stub_course_search,
) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)
    owned = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text",
        "student",
        {"text": "경사하강법이 뭐야?"},
    ).json()

    # The professor can access the course but not another learner's conversation.
    reset_context(chat_api.users["professor"], course_id)
    response = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text",
        "professor",
        {"text": "이어서 물어볼게요", "chat_session_id": owned["session_id"]},
    )

    assert response.status_code == 404


def test_reset_clears_the_conversation(chat_api) -> None:
    response = chat_api.post(
        f"/api/voice/courses/{chat_api.courses['ai']}/reset", "student", {}
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
