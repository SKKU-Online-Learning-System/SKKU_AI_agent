"""Weak-concept statistics for professors and administrators."""

from __future__ import annotations

import json
import time
from pathlib import Path

from tests.conftest import ChatApiContext

DAY = 86_400
LEARNING_RATE = "학습률 - 너무 크면 발산하는 이유"
SOFTMAX = "소프트맥스 - 합이 1인 확률로 바꾸는 계산"
BACKPROP = "역전파 - 연쇄법칙 적용"
COHESION = "응집도 - 결합도와의 차이"


def _record(memory_id: str, student_id: str, course: str, concept: str, **fields) -> dict:
    return {
        "id": memory_id,
        "student_id": student_id,
        "course": course,
        "concept": concept,
        "original_question": f"{concept.split(' - ')[0]}이 뭔지 모르겠어",
        "difficulty_note": f"{concept.split(' - ')[0]} 이해에 어려움을 보임",
        **fields,
    }


def seed_weak_concepts(chat_api: ChatApiContext, tmp_path: Path) -> float:
    now = time.time()
    student = chat_api.users["student"]
    other = chat_api.users["other_student"]
    records = [
        _record("M-1", student, "인공지능개론", LEARNING_RATE, status="new", confidence=0.0,
                failure_count=1, success_count=0, saved_at=now - 2 * DAY,
                last_seen_at=now - 2 * DAY, next_review_at=now - DAY),
        _record("M-2", other, "인공지능개론", LEARNING_RATE, status="practicing", confidence=0.34,
                failure_count=2, success_count=1, saved_at=now - DAY,
                last_seen_at=now - 3_600, next_review_at=now + DAY),
        _record("M-3", student, "인공지능개론", SOFTMAX, status="mastered", confidence=1.0,
                failure_count=1, success_count=3, saved_at=now - 3 * DAY,
                last_seen_at=now - 7_200, next_review_at=now + 30 * DAY),
        _record("M-4", other, "소프트웨어공학", COHESION, status="new", confidence=0.0,
                failure_count=1, success_count=0, saved_at=now - DAY,
                last_seen_at=now - DAY, next_review_at=now + DAY),
        _record("M-5", "ghost-user", "인공지능개론", BACKPROP, status="new", confidence=0.0,
                failure_count=1, success_count=0, saved_at=now - 4 * DAY,
                last_seen_at=now - 4 * DAY, next_review_at=now - 3 * DAY),
    ]
    path = tmp_path / "uploads" / "voice" / "weak-concepts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return now


def test_professor_overview_counts_only_assigned_courses(chat_api: ChatApiContext, tmp_path) -> None:
    seed_weak_concepts(chat_api, tmp_path)

    response = chat_api.get("/api/stats/weak-concepts", "professor")

    assert response.status_code == 200
    body = response.json()
    assert [course["courseName"] for course in body["courses"]] == ["인공지능개론"]
    ai = body["courses"][0]
    assert ai["courseId"] == chat_api.courses["ai"]
    assert ai["recordCount"] == 4
    assert ai["conceptCount"] == 3
    assert ai["studentCount"] == 3
    assert ai["statusCounts"] == {"new": 2, "practicing": 1, "mastered": 1}
    assert ai["averageMastery"] == 34
    assert ai["dueReviewCount"] == 2
    assert ai["lastActivityAt"] is not None
    assert body["totals"]["courseCount"] == 1
    assert body["totals"]["recordCount"] == 4


def test_admin_overview_covers_every_course(chat_api: ChatApiContext, tmp_path) -> None:
    seed_weak_concepts(chat_api, tmp_path)

    response = chat_api.get("/api/stats/weak-concepts", "admin")

    assert response.status_code == 200
    body = response.json()
    assert {course["courseName"] for course in body["courses"]} == {"인공지능개론", "소프트웨어공학"}
    assert body["totals"]["courseCount"] == 2
    assert body["totals"]["recordCount"] == 5
    assert body["totals"]["studentCount"] == 3


def test_overview_is_empty_without_a_memory_file(chat_api: ChatApiContext) -> None:
    response = chat_api.get("/api/stats/weak-concepts", "professor")

    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["recordCount"] == 0
    assert body["courses"][0]["recordCount"] == 0
    assert body["courses"][0]["lastActivityAt"] is None


def test_course_detail_ranks_concepts_and_masks_students_for_professors(
    chat_api: ChatApiContext, tmp_path
) -> None:
    seed_weak_concepts(chat_api, tmp_path)

    response = chat_api.get(f"/api/stats/weak-concepts/courses/{chat_api.courses['ai']}", "professor")

    assert response.status_code == 200
    body = response.json()
    assert body["courseName"] == "인공지능개론"
    assert body["recordCount"] == 4

    concepts = body["concepts"]
    assert [row["concept"] for row in concepts] == [LEARNING_RATE, SOFTMAX, BACKPROP]
    assert concepts[0]["topic"] == "학습률"
    assert concepts[0]["detail"] == "너무 크면 발산하는 이유"
    assert concepts[0]["studentCount"] == 2
    assert concepts[0]["failureCount"] == 3
    assert concepts[0]["successCount"] == 1
    assert concepts[0]["statusCounts"] == {"new": 1, "practicing": 1, "mastered": 0}
    assert concepts[0]["averageMastery"] == 17
    assert concepts[0]["sampleNotes"] == ["학습률 이해에 어려움을 보임"]

    assert body["topics"][0] == {
        "topic": "학습률",
        "conceptCount": 1,
        "studentCount": 2,
        "failureCount": 3,
        "averageMastery": 17,
    }

    students = body["students"]
    assert students[0]["conceptCount"] == 2
    assert students[0]["averageMastery"] == 50
    assert students[0]["dueReviewCount"] == 1
    assert students[0]["weakestConcepts"][0] == LEARNING_RATE
    assert {row["label"] for row in students} == {"ch***@skku.edu", "삭제된 사용자"}
    assert "chat-student@skku.edu" not in response.text

    assert sum(item["count"] for item in body["savedByDate"]) == 4
    assert len(body["recentCaptures"]) == 4
    assert body["recentCaptures"][0]["concept"] == LEARNING_RATE
    assert body["recentCaptures"][0]["status"] == "practicing"
    assert body["recentCaptures"][0]["studentLabel"] == "ch***@skku.edu"


def test_admin_detail_reveals_identity_and_access_is_role_scoped(
    chat_api: ChatApiContext, tmp_path
) -> None:
    seed_weak_concepts(chat_api, tmp_path)
    ai, se = chat_api.courses["ai"], chat_api.courses["se"]

    admin = chat_api.get(f"/api/stats/weak-concepts/courses/{ai}", "admin")
    assert admin.status_code == 200
    assert "chat-student@skku.edu" in {row["label"].split(" ")[0] for row in admin.json()["students"]}

    assert chat_api.get(f"/api/stats/weak-concepts/courses/{se}", "professor").status_code == 403
    assert chat_api.get("/api/stats/weak-concepts", "student").status_code == 403
    assert chat_api.get(f"/api/stats/weak-concepts/courses/{ai}", "student").status_code == 403
    assert chat_api.get("/api/stats/weak-concepts/courses/missing", "admin").status_code == 404


def test_course_matching_ignores_unicode_normalization_and_whitespace() -> None:
    import unicodedata

    from app.services import weak_concept_stats

    decomposed = unicodedata.normalize("NFD", "인공지능개론")
    memories = [
        {"course": decomposed, "concept": LEARNING_RATE, "student_id": "s1"},
        {"course": " 인공지능개론 ", "concept": SOFTMAX, "student_id": "s2"},
        {"course": "소프트웨어공학", "concept": COHESION, "student_id": "s3"},
        {"course": "인공지능개론", "concept": "   ", "student_id": "s4"},
    ]

    matched = weak_concept_stats.course_memories(memories, "인공지능개론")

    assert [memory["concept"] for memory in matched] == [LEARNING_RATE, SOFTMAX]
