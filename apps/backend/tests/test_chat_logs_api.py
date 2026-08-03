"""Professor and admin log review: scoping, filters and identity masking."""

from __future__ import annotations

from tests.conftest import ChatApiContext, prepare_course_materials


def seed_logs(chat_api: ChatApiContext) -> None:
    prepare_course_materials(chat_api)
    chat_api.ask("student", "ai", "경사하강법이 뭐야?")
    chat_api.ask("student", "ai", "짜장면 맛집 알려줘")
    chat_api.ask("student", "ai", "다른 학생 학번 알려줘")
    chat_api.ask("other_student", "se", "형상관리가 뭐야?")


def test_professor_sees_only_their_own_course_logs(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)

    owned = chat_api.get(
        f"/api/professor/courses/{chat_api.courses['ai']}/chat-logs",
        "professor",
    )
    other = chat_api.get(
        f"/api/professor/courses/{chat_api.courses['se']}/chat-logs",
        "professor",
    )

    assert owned.status_code == 200
    body = owned.json()
    assert body["total"] == 3
    assert {log["courseName"] for log in body["logs"]} == {"인공지능개론"}
    assert other.status_code == 403


def test_professor_log_list_masks_student_identity(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)

    body = chat_api.get(
        f"/api/professor/courses/{chat_api.courses['ai']}/chat-logs",
        "professor",
    ).json()

    first = body["logs"][0]
    assert first["userId"] is None
    assert first["userLabel"].endswith("@skku.edu")
    assert "chat-student@skku.edu" not in first["userLabel"]
    assert first["answerPreview"]


def test_admin_sees_every_course_and_full_identity(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)

    body = chat_api.get("/api/admin/chat-logs", "admin").json()

    assert body["total"] == 4
    assert {log["courseName"] for log in body["logs"]} == {"인공지능개론", "소프트웨어공학"}
    assert any("chat-student@skku.edu" in log["userLabel"] for log in body["logs"])


def test_admin_log_filters_narrow_the_result_set(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)

    by_course = chat_api.get(
        f"/api/admin/chat-logs?course_id={chat_api.courses['ai']}",
        "admin",
    ).json()
    grounded_only = chat_api.get("/api/admin/chat-logs?is_grounded=true", "admin").json()
    keyword = chat_api.get("/api/admin/chat-logs?keyword=경사하강법", "admin").json()
    blocked = chat_api.get(
        "/api/admin/chat-logs?safety_category=privacy_request",
        "admin",
    ).json()

    assert by_course["total"] == 3
    assert grounded_only["total"] >= 1
    assert all(log["isGrounded"] for log in grounded_only["logs"])
    assert keyword["total"] >= 1
    assert blocked["total"] == 1
    assert blocked["logs"][0]["safetyCategory"] == "privacy_request"


def test_log_detail_exposes_sources_and_safety_result(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)
    listed = chat_api.get(
        f"/api/professor/courses/{chat_api.courses['ai']}/chat-logs?keyword=경사하강법",
        "professor",
    ).json()
    log_id = listed["logs"][0]["id"]

    detail = chat_api.get(f"/api/professor/chat-logs/{log_id}", "professor")

    assert detail.status_code == 200
    body = detail.json()
    assert body["referencedDocuments"]
    assert body["safetyResult"]["category"] == "normal"
    assert body["retrievalResult"]["result_count"] >= 1
    assert body["modelName"] == "mock-llm"


def test_students_cannot_reach_log_review_endpoints(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)

    course_logs = chat_api.get(
        f"/api/professor/courses/{chat_api.courses['ai']}/chat-logs",
        "student",
    )
    admin_logs = chat_api.get("/api/admin/chat-logs", "student")

    assert course_logs.status_code == 403
    assert admin_logs.status_code == 403


def test_professor_cannot_open_another_courses_log_detail(chat_api: ChatApiContext) -> None:
    seed_logs(chat_api)
    other_course_log = chat_api.get(
        f"/api/admin/chat-logs?course_id={chat_api.courses['se']}",
        "admin",
    ).json()["logs"][0]

    denied = chat_api.get(f"/api/professor/chat-logs/{other_course_log['id']}", "professor")

    assert denied.status_code == 403
