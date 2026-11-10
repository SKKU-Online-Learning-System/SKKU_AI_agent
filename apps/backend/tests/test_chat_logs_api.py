"""A course assignment or administrator role cannot grant transcript access."""

import pytest

from tests.conftest import ChatApiContext, prepare_course_materials


def test_only_owner_can_read_the_conversation(chat_api: ChatApiContext) -> None:
    prepare_course_materials(chat_api)
    question = "경사하강법이 뭐야?"
    reply = chat_api.ask("student", "ai", question).json()
    path = f"/api/chat/sessions/{reply['sessionId']}"
    own = chat_api.get(path, "student")

    assert own.status_code == 200
    assert own.headers["cache-control"] == "private, no-store"
    turn = own.json()["logs"][0]
    assert turn["question"] == question
    assert turn["answer"] == reply["answer"]
    assert turn["sources"]
    for role in ("professor", "admin", "other_student"):
        assert chat_api.get(path, role).status_code in (403, 404)
        assert chat_api.get("/api/chat/sessions", role).json() == []

    own_logs = chat_api.get("/api/student/chat-logs?keyword=경사하강법", "student")
    assert own_logs.json()["logs"][0]["question"] == question
    assert chat_api.get("/api/student/chat-logs", "other_student").json()["total"] == 0
    assert chat_api.get("/api/student/chat-logs", "admin").status_code == 403


@pytest.mark.parametrize(
    ("role", "path"),
    [
        ("professor", "/api/professor/courses/{course}/chat-logs"),
        ("professor", "/api/professor/chat-logs/example"),
        ("admin", "/api/admin/chat-logs"),
        ("admin", "/api/admin/chat-logs/example"),
        ("professor", "/api/stats/weak-concepts"),
        ("admin", "/api/stats/weak-concepts/courses/{course}"),
    ],
)
def test_legacy_staff_transcript_and_learner_capture_endpoints_are_gone(
    chat_api: ChatApiContext, role: str, path: str,
) -> None:
    assert chat_api.get(path.format(course=chat_api.courses["ai"]), role).status_code == 404
