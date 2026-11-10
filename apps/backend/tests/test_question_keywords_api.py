"""Only recurring approved terms are visible, in the relevant course week."""

from app.models import ChatLog, ChatSession, CourseMaterial, UserRole
from tests.conftest import ChatApiContext, add_user, prepare_course_materials


def test_course_keywords_are_suppressed_per_week_and_student(chat_api: ChatApiContext) -> None:
    material_id = prepare_course_materials(chat_api)
    course_id = chat_api.courses["ai"]
    with chat_api.session_factory() as db:
        material = db.get(CourseMaterial, material_id)
        material.week = 2
        foreign = db.query(CourseMaterial).filter_by(course_id=chat_api.courses["se"]).one()
        other_week = CourseMaterial(
            course_id=course_id,
            uploaded_by=material.uploaded_by,
            file_name="week3.txt",
            original_file_name="week3.txt",
            file_type="txt",
            file_size=1,
            week=3,
            storage_path="week3.txt",
            processing_status=material.processing_status,
        )
        db.add(other_week)
        db.flush()

        def record(user_id, question, *, focus=None, cite=None, category="normal"):
            history = ChatSession(user_id=user_id, course_id=course_id)
            db.add(history)
            db.flush()
            db.add(ChatLog(
                user_id=user_id, course_id=course_id, session_id=history.id,
                question=question, answer="개인 답변 원문",
                referenced_documents=[{"material_id": cite}] if cite else [],
                retrieval_result={"focus_material_id": focus} if focus else {},
                safety_result={"category": category},
            ))

        students = [
            add_user(db, f"keyword-test-{i}@skku.edu", UserRole.student).id for i in range(5)
        ]
        for i, student in enumerate(students):
            record(
                student, "경사하강법과 경사하강법이 어려워요. 비공개이름",
                focus=material_id if i < 4 else None,
                cite=other_week.id if i < 4 else material_id,
            )
            if i < 4:
                record(student, "경사하강법", focus=other_week.id)
            record(student, "신경망", focus=foreign.id)
        record(students[0], "경사하강법, SQL과 ＳＱＬ은?", focus=material_id)
        for _ in range(6):
            record(students[0], "과적합", focus=material_id)
        record(students[4], "경사하강법", focus=other_week.id, category="privacy_request")
        record(chat_api.users["professor"], "경사하강법", focus=other_week.id)
        db.commit()

    path = f"/api/stats/courses/{course_id}/keywords"
    expected = {
        "courseId": course_id,
        "weeks": [{"week": 2, "keywords": [{"keyword": "경사하강법", "questionCount": 6}]}],
    }
    assert chat_api.get(path, "professor").json() == expected
    assert chat_api.get(path, "admin").json() == expected
    assert chat_api.get(path, "other_professor").status_code == 403
    assert chat_api.get(path, "student").status_code == 403
    assert chat_api.get("/api/stats/courses/missing/keywords", "admin").status_code == 404
