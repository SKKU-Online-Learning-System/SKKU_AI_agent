"""The study page's 교안 pages and their AI 해설, and the page the chat is focused on."""
import asyncio
from io import BytesIO
from unittest.mock import AsyncMock

from PIL import Image, ImageDraw

from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from app.services.voice import brain
from app.services.voice.session_store import VoiceContext


def _upload_scanned_pdf(chat_api, monkeypatch) -> tuple[str, str]:
    image = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(image).text((40, 40), "Softmax", fill="black")
    pdf = BytesIO()
    image.save(pdf, format="PDF")
    monkeypatch.setattr(EmbeddingService, "embed_image", lambda self, url: [1.0, 0.0])
    monkeypatch.setattr(EmbeddingService, "embed_text", lambda *a: [1.0, 0.0])
    monkeypatch.setattr(
        LLMService, "read_document_image",
        lambda self, url, question="": "소프트맥스 정의\n- 확률 분포로 정규화\n- 분모는 지수 합",
    )
    course_id = chat_api.courses["ai"]
    uploaded = chat_api.client.post(
        f"/api/courses/{course_id}/materials", headers=chat_api.headers("professor"),
        files={"file": ("week1.pdf", pdf.getvalue(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    material_id = uploaded.json()["id"]
    assert chat_api.process("professor", "ai", material_id).status_code == 200
    return course_id, material_id


def test_pages_and_note_are_course_scoped_and_cached(chat_api, monkeypatch):
    course_id, material_id = _upload_scanned_pdf(chat_api, monkeypatch)
    pages_url = f"/api/courses/{course_id}/materials/{material_id}/pages"
    listed = chat_api.get(pages_url, "student")
    assert listed.status_code == 200
    assert listed.json() == {
        "material_id": material_id, "file": "week1.pdf", "pages": [1], "noted": [],
    }
    assert chat_api.get(pages_url, "other_student").status_code == 403

    calls = []
    original = LLMService.generate_json

    async def counted(self, **kwargs):
        calls.append(kwargs["payload"])
        return await original(self, **kwargs)

    monkeypatch.setattr(LLMService, "generate_json", counted)
    note_url = f"{pages_url}/1/note"
    first = chat_api.get(note_url, "student")
    assert first.status_code == 200
    body = first.json()
    assert body["page"] == 1
    assert body["title"] == "1쪽 핵심 정리"
    assert body["summary"] == "소프트맥스 정의"
    assert [point["label"] for point in body["points"]][:2] == ["소프트맥스 정의", "확률 분포로 정규화"]
    assert calls[0]["page_text"].startswith("소프트맥스 정의")
    # The second reader gets the cached note: no second model call.
    assert chat_api.get(note_url, "student").json() == body
    assert len(calls) == 1
    assert chat_api.get(pages_url, "student").json()["noted"] == [1]
    assert chat_api.get(f"{pages_url}/9/note", "student").status_code == 404
    assert chat_api.get(note_url, "other_student").status_code == 403


def test_prefetch_supplies_the_page_the_student_is_viewing(monkeypatch):
    monkeypatch.setattr(brain, "page_focus", lambda course_id, material_id, page: {
        "source": "week1.pdf p.3", "file": "week1.pdf", "page": page,
        "material_id": material_id, "excerpt": "경사하강법 수식",
    })

    async def no_memory(context, topic=""):
        return {"found": False, "memories": []}

    monkeypatch.setattr(brain, "recent_weak_concepts", no_memory)
    monkeypatch.setattr(
        brain, "search_course_materials", lambda course_id, query: ('{"found": false}', [])
    )
    context = VoiceContext(user_id="u", course_id="c", course_name="AI", memory=AsyncMock())
    plain = asyncio.run(brain.prefetch_context(context, "경사하강법이 뭐야?"))
    assert "viewing_page" not in plain
    focused = asyncio.run(brain.prefetch_context(
        context, "이 슬라이드 수식 설명해줘", focus={"material_id": "m", "page": 3}
    ))
    assert focused["viewing_page"]["page"] == 3
    assert focused["viewing_page"]["excerpt"] == "경사하강법 수식"
    assert "viewing_page" in brain.answer_instructions(context, focused)
