"""Offline checks of the real multimodal ingestion/retrieval boundary."""
import base64
from io import BytesIO
import json

import httpx
from PIL import Image, ImageDraw
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import DocumentChunk
from app.services.embedding_service import EmbeddingError, EmbeddingService
from app.services.llm_service import LLMError, LLMService
from app.services.rag_service import RagService


def test_qwen_embedding_sends_image_and_rejects_invalid_vectors(monkeypatch):
    requests = []
    values = [1.0] * 2048

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": values}]})

    client = httpx.Client(transport=httpx.MockTransport(respond), base_url="http://model/v1/")
    monkeypatch.setattr("app.services.embedding_service.sync_client", lambda *a: client)
    service = EmbeddingService(Settings(_env_file=None))
    vector = service.embed_image("data:image/jpeg;base64,YQ==")
    assert len(vector) == 2048
    assert sum(x*x for x in vector) == pytest.approx(1)
    assert requests[0]["add_special_tokens"] is True
    assert requests[0]["messages"][1]["content"][0]["type"] == "image_url"
    values[:] = [0.0] * 2048
    with pytest.raises(EmbeddingError):
        service.embed_text("question")
    values[:] = [1.0] * 512
    with pytest.raises(EmbeddingError):
        service.embed_text("question")


def test_scanned_page_ingestion_reading_source_access_and_stale_index(chat_api, monkeypatch):
    image = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(image).text((40, 40), "Learning rate 0.1 -> loss 1.2", fill="black")
    pdf = BytesIO()
    image.save(pdf, format="PDF")
    seen_images = []
    readings = []

    def embed_image(self, url):
        seen_images.append(url)
        return [1.0, 0.0]

    def read_image(self, url, question=""):
        assert base64.b64decode(url.split(",", 1)[1]).startswith(b"\xff\xd8")
        assert question == ""
        readings.append(url)
        return "학습률 0.1 → 손실 1.2."

    monkeypatch.setattr(EmbeddingService, "embed_image", embed_image)
    monkeypatch.setattr(EmbeddingService, "embed_text", lambda *a: [1.0, 0.0])
    monkeypatch.setattr(LLMService, "read_document_image", read_image)
    course_id = chat_api.courses["ai"]
    uploaded = chat_api.client.post(
        f"/api/courses/{course_id}/materials", headers=chat_api.headers("professor"),
        files={"file": ("scan.pdf", pdf.getvalue(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    material_id = uploaded.json()["id"]
    assert chat_api.process("professor", "ai", material_id).status_code == 200
    assert len(seen_images) == 1
    assert len(readings) == 1
    result = chat_api.post("/api/rag/search", "student", {
        "courseId": course_id, "question": "학습률 0.1의 손실은?",
    })
    assert result.status_code == 200
    assert len(readings) == 1
    assert "1.2" in result.json()["results"][0]["chunkText"]
    assert result.json()["results"][0]["pageNumber"] == 1
    page_url = f"/api/courses/{course_id}/materials/{material_id}/pages/1/image"
    assert result.json()["results"][0]["pageImageUrl"] == page_url
    assert chat_api.get(page_url, "student").headers["content-type"] == "image/jpeg"
    assert chat_api.get(page_url, "other_student").status_code == 403
    assert chat_api.get(page_url.replace(course_id, chat_api.courses["se"]), "admin").status_code == 404
    # Repeated turns use stored evidence, without another image-model call.
    chat_api.post("/api/rag/search", "student", {
        "courseId": course_id, "question": "표의 손실 값은?",
    })
    assert len(readings) == 1
    with chat_api.session_factory() as session:
        rag = RagService(session, Settings(embedding_provider="mock"))
        with pytest.raises(ValueError, match="not found"):
            rag.inspect_page(chat_api.courses["se"], material_id, 1, "missing value")
        with pytest.raises(ValueError, match="not found"):
            rag.inspect_page(course_id, material_id, 99, "missing value")
        with pytest.raises(ValueError):
            rag.inspect_page(course_id, material_id, True, "missing value")
        monkeypatch.setattr(LLMService, "read_document_image", lambda self, url, question="": (
            "원본 재확인: " + question
        ))
        assert "loss" in rag.inspect_page(course_id, material_id, 1, "loss")
        old = session.scalar(select(DocumentChunk).where(DocumentChunk.material_id == material_id))
        old_id, old_evidence = old.id, old.page_evidence

    inspect_url = f"/api/courses/{course_id}/materials/{material_id}/pages/1/inspect"
    inspected = chat_api.post(inspect_url, "student", {"question": "loss"})
    assert inspected.status_code == 200
    assert inspected.json()["file"] == "scan.pdf"
    assert "loss" in inspected.json()["evidence"]
    assert chat_api.post(inspect_url, "other_student", {"question": "loss"}).status_code == 403
    assert chat_api.post(inspect_url, "student", {"question": ""}).status_code == 422
    assert chat_api.post(inspect_url.replace("/1/", "/99/"), "student", {
        "question": "loss",
    }).status_code == 404

    def fail_read(*args):
        raise LLMError("image server unavailable")

    monkeypatch.setattr(LLMService, "read_document_image", fail_read)
    assert chat_api.process("professor", "ai", material_id, "reprocess").status_code == 422
    with chat_api.session_factory() as session:
        old = session.get(DocumentChunk, old_id)
        assert old.page_evidence == old_evidence
    monkeypatch.setattr(LLMService, "read_document_image", read_image)
    assert chat_api.process("professor", "ai", material_id, "reprocess").status_code == 200
    with chat_api.session_factory() as session:
        assert session.get(DocumentChunk, old_id) is None
    assert len(readings) == 2
    with chat_api.session_factory() as session:
        chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.material_id == material_id))
        chunk.embedding_model = "old-hash-model"
        session.commit()
    assert not chat_api.get(f"/api/courses/{course_id}/rag/status", "student").json()["isSearchReady"]
    result = chat_api.post("/api/rag/search", "student", {
        "courseId": course_id, "question": "학습률 0.1의 손실은?",
    })
    assert result.json()["results"] == []


@pytest.mark.parametrize("content,expected", [(b"Lecture about attention", "completed"), (b"Lecture with unavailable embedding server", "failed")])
def test_upload_prepares_material_in_background(chat_api, monkeypatch, content, expected):
    from app.api.routes import materials
    from app.services.material_processing_service import process_uploaded_material

    monkeypatch.setattr(materials, "process_uploaded_material", process_uploaded_material)
    if expected == "failed":
        def unavailable(*args):
            raise EmbeddingError("server unavailable")
        monkeypatch.setattr(EmbeddingService, "embed_texts", unavailable)
    course_id = chat_api.courses["ai"]
    response = chat_api.client.post(
        f"/api/courses/{course_id}/materials", headers=chat_api.headers("professor"),
        files={"file": ("auto.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["processingStatus"] == "pending"
    material_id = response.json()["id"]
    # TestClient waits for BackgroundTasks; the HTTP response snapshot is still pending.
    status = chat_api.get(
        f"/api/courses/{course_id}/materials/{material_id}/processing-status", "professor",
    ).json()
    assert status["processingStatus"] == expected
    assert bool(status["processingError"]) == (expected == "failed")
