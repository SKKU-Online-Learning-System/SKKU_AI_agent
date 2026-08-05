"""Role-scoped statistics and student log history."""

from tests.conftest import ChatApiContext, prepare_course_materials


def seed_usage(chat_api: ChatApiContext) -> None:
    prepare_course_materials(chat_api)
    assert chat_api.ask("student", "ai", "경사하강법이 뭐야?").status_code == 200
    assert chat_api.ask("student", "ai", "지도학습을 설명해줘").status_code == 200
    assert chat_api.ask("other_student", "se", "형상관리가 뭐야?").status_code == 200


def test_admin_service_statistics_include_required_breakdowns(chat_api: ChatApiContext) -> None:
    seed_usage(chat_api)

    response = chat_api.get("/api/stats/service", "admin")

    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {"courseCount": 2, "userCount": 5, "questionCount": 3}
    assert sum(item["count"] for item in body["questionsByDate"]) == 3
    assert {item["courseName"] for item in body["courses"]} == {
        "인공지능개론",
        "소프트웨어공학",
    }
    ai = next(item for item in body["courses"] if item["courseName"] == "인공지능개론")
    assert ai["questionCount"] == 2
    assert ai["userCount"] == 1
    assert ai["materialCount"] == 1


def test_professor_statistics_are_limited_to_assigned_courses(chat_api: ChatApiContext) -> None:
    seed_usage(chat_api)

    response = chat_api.get("/api/stats/professor", "professor")

    assert response.status_code == 200
    body = response.json()
    assert [course["courseName"] for course in body["courses"]] == ["인공지능개론"]
    assert len(body["recentQuestions"]) == 2
    assert body["keywords"]
    assert chat_api.get("/api/stats/professor", "student").status_code == 403


def test_course_statistics_enforce_professor_assignment(chat_api: ChatApiContext) -> None:
    seed_usage(chat_api)

    owned = chat_api.get(f"/api/stats/courses/{chat_api.courses['ai']}", "professor")
    denied = chat_api.get(f"/api/stats/courses/{chat_api.courses['se']}", "professor")

    assert owned.status_code == 200
    assert owned.json()["questionCount"] == 2
    assert denied.status_code == 403


def test_student_statistics_and_logs_never_expose_other_users(chat_api: ChatApiContext) -> None:
    seed_usage(chat_api)

    statistics = chat_api.get("/api/stats/me", "student")
    logs = chat_api.get("/api/student/chat-logs", "student")
    filtered = chat_api.get(
        f"/api/student/chat-logs?course_id={chat_api.courses['se']}",
        "student",
    )

    assert statistics.status_code == 200
    assert statistics.json()["questionCount"] == 2
    assert logs.status_code == 200
    assert logs.json()["total"] == 2
    assert {item["userId"] for item in logs.json()["logs"]} == {chat_api.users["student"]}
    assert filtered.status_code == 403


def test_log_user_filter_is_scoped_by_role(chat_api: ChatApiContext) -> None:
    seed_usage(chat_api)

    professor = chat_api.get(
        "/api/professor/courses/"
        f"{chat_api.courses['ai']}/chat-logs?user_id={chat_api.users['student']}",
        "professor",
    )
    admin = chat_api.get(
        f"/api/admin/chat-logs?user_id={chat_api.users['other_student']}",
        "admin",
    )

    assert professor.status_code == 200
    assert professor.json()["total"] == 2
    assert admin.status_code == 200
    assert admin.json()["total"] == 1
