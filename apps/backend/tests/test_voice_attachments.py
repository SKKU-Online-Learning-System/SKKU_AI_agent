"""The text agent shows its work and reads the files a student attaches.

Two things the typed COURSE AGENT path does that the voice path does not: it
streams a trace of what it is doing (``step``) and the model's reasoning
(``thinking``) before the answer, and it accepts images and PDFs with the
question. Both are covered here against the deterministic mock, plus the unit
behaviour of the attachment reader against a stub vision model.
"""

from __future__ import annotations

import json
import zlib
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select

from app.api.routes import voice as voice_routes
from app.core.config import Settings, get_settings
from app.main import app
from app.models import ChatLog
from pathlib import Path

from app.services.llm_service import LLMError
from app.services.voice import attachments, brain, external_brain, trusted_sites
from app.services.voice.session_store import get_context, reset_context

MOCK_SETTINGS = Settings(_env_file=None, use_mock_llm=True)
LONG_LINE = (
    "Gradient descent updates the parameters in the direction opposite to the gradient "
    "of the loss so that the loss decreases step by step."
)


@pytest.fixture(autouse=True)
def isolated_voice_state(tmp_path, monkeypatch):
    """Keep the brain on the mock model; the routes get the fixture's settings via Depends."""
    monkeypatch.setattr(trusted_sites, "voice_storage_dir", lambda: tmp_path / "voice")
    monkeypatch.setattr(external_brain, "get_settings", lambda: MOCK_SETTINGS)
    monkeypatch.setattr(brain, "get_settings", lambda: MOCK_SETTINGS)


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
    queries: list[str] = []

    def search(_course_id, query):
        queries.append(query)
        return result, citations

    monkeypatch.setattr(brain, "search_course_materials", search)
    return queries


def png_bytes(size: tuple[int, int] = (64, 48)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(output, format="PNG")
    return output.getvalue()


def text_pdf(pages: list[list[str]]) -> bytes:
    """A minimal PDF with one Helvetica text page per entry; [] makes a blank page."""

    def escape(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects: list[str] = []
    page_ids: list[int] = []
    # 1 catalog, 2 pages, 3 font, then (page, content) pairs.
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("PAGES")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for lines in pages:
        content = "BT /F1 12 Tf 50 750 Td 14 TL " + " ".join(
            f"({escape(line)}) Tj T*" for line in lines
        ) + " ET"
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"

    out = "%PDF-1.4\n"
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{index} 0 obj\n{obj}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def _pdf_from_objects(objects: list[str]) -> bytes:
    out = "%PDF-1.4\n"
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out.encode("latin-1")))
        out += f"{index} 0 obj\n{obj}\nendobj\n"
    xref = len(out.encode("latin-1"))
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def flate_bomb_pdf(chars: int = 20_000_000) -> bytes:
    """One page whose Flate content stream inflates to ``chars`` bytes of text operators."""
    content = zlib.compress(b"BT /F1 12 Tf 50 750 Td " + b"(AAAAAAAA) Tj " * (chars // 14) + b"ET", 9)
    stream = f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode("latin-1")
    stream += content + b"\nendstream"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        stream.decode("latin-1"),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    return _pdf_from_objects(objects)


def huge_image_pdf() -> bytes:
    """One page referencing an image XObject whose header says 60000 x 60000 pixels."""
    content = "q 612 0 0 792 0 0 cm /Im1 Do Q"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /XObject << /Im1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /XObject /Subtype /Image /Width 60000 /Height 60000 /ColorSpace /DeviceGray "
        "/BitsPerComponent 8 /Length 1 >>\nstream\n\x00\nendstream",
    ]
    return _pdf_from_objects(objects)


def upload(chat_api, user: str, course: str, name: str, data: bytes, media_type: str):
    return chat_api.client.post(
        f"/api/voice/courses/{chat_api.courses[course]}/attachments",
        headers=chat_api.headers(user),
        files={"file": (name, data, media_type)},
    )


def stream(chat_api, user: str, course: str, payload: dict) -> list[dict]:
    response = chat_api.client.post(
        f"/api/voice/courses/{chat_api.courses[course]}/answer-text/stream",
        headers=chat_api.headers(user),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines()]


def steps(events: list[dict]) -> dict[str, dict]:
    """The final state of every trace step, by key."""
    final: dict[str, dict] = {}
    for event in events:
        if event["type"] == "step":
            final[event["key"]] = event
    return final


# --------------------------------------------------------------------------
# The trace: what the agent is doing, and what the model is thinking
# --------------------------------------------------------------------------


def test_text_stream_reports_each_step_and_the_models_reasoning(
    chat_api, stub_course_search, monkeypatch
) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)
    monkeypatch.setattr(voice_routes, "SessionLocal", chat_api.session_factory)

    events = stream(chat_api, "student", "ai", {"text": "경사하강법이 뭐야?"})

    kinds = [event["type"] for event in events]
    # Every step is announced before the first answer token, in the order the
    # agent works: evidence first, then the model.
    first_token = kinds.index("token")
    assert kinds[-1] == "done"
    assert all(kind in {"status", "step", "thinking"} for kind in kinds[:first_token])
    running = [e for e in events if e["type"] == "step" and e["state"] == "running"]
    assert [e["key"] for e in running] == ["recall", "material", "llm-1"]
    assert running[1]["detail"] == "경사하강법이 뭐야?"

    final = steps(events)
    assert final["material"]["state"] == "done"
    assert final["material"]["label"] == "강의자료 1곳을 찾았어요"
    assert final["material"]["detail"] == "lecture1.txt"
    assert "elapsed_ms" in final["material"]
    assert final["recall"]["label"] == "참고할 취약 개념이 없어요"
    assert final["llm-1"]["stage"] == "llm"
    assert final["llm-1"]["label"] == "답변을 정리했어요"

    # The mock reasons too, so the panel is exercised with no model server. The
    # reasoning is shown, never part of the reply, and hangs under its round.
    thinking = "".join(e["text"] for e in events if e["type"] == "thinking")
    assert "[모의 추론]" in thinking
    assert all(e["key"] == "llm-1" for e in events if e["type"] == "thinking")
    assert "[모의 추론]" not in events[-1]["reply"]
    assert events[-1]["attachments"] == []


def test_the_round_detail_splits_thinking_from_writing() -> None:
    assert brain._timing_detail(10.0, 14.12, 16.2) == "생각 4.1초 · 작성 2.1초"
    assert brain._timing_detail(10.0, None, 16.2) == ""
    # No thinking worth naming (the mock, or thinking off): no detail.
    assert brain._timing_detail(10.0, 10.01, 12.0) == ""
    label, detail, _state = brain._tool_step_labels(
        "recall_weak_concepts", {},
        {"memories": [{"concept": "안녕하세요! 인공지능 개론 수업에 오신 것을 환영합니다. 오늘 어떤 부분이"}]},
    )
    assert label == "취약 개념 1개를 참고해요"
    assert detail == "안녕하세요! 인공지능 개론 수업에 오신 것…" and len(detail) == 24


def test_step_labels_describe_tool_outcomes_without_model_text() -> None:
    label, detail, state = brain._tool_step_labels(
        "search_trusted_web",
        {"query": "attention"},
        {"found": True, "sources": ["https://www.arxiv.org/abs/1", "https://kosis.kr/x"]},
    )
    assert (label, detail, state) == ("웹 출처 2개를 찾았어요", "arxiv.org, kosis.kr", "done")

    label, detail, state = brain._tool_step_labels(
        "show_visualization", {}, {"kind": "formula", "title": "소프트맥스"}
    )
    assert (label, detail, state) == ("수식을 준비했어요", "소프트맥스", "done")
    assert brain._tool_step_labels("show_visualization", {}, {"kind": "flow"})[0] == (
        "흐름도를 준비했어요"
    )

    label, detail, state = brain._tool_step_labels(
        "show_visualization", {}, {"error": "invalid show_visualization arguments: got 'foo'"}
    )
    assert (label, detail, state) == ("시각 자료를 표시하지 못했어요", "도구 인자가 올바르지 않았어요", "failed")
    # An exception message is for the model, never for the screen.
    label, detail, state = brain._tool_step_labels(
        "search_trusted_web", {}, {"error": "ConnectError: http://searxng:8080 refused"}
    )
    assert (label, detail, state) == ("웹 검색에서 근거를 찾지 못했어요", "", "failed")
    assert brain._tool_step_labels(
        "search_trusted_web", {}, {"error": "trusted web search returned no citable sources"}
    )[1] == "인용할 수 있는 출처가 없었어요"


@pytest.mark.asyncio
async def test_think_traces_each_tool_round(monkeypatch) -> None:
    """Every model round and every tool call gets its own line, updated in place."""
    from unittest.mock import AsyncMock

    from app.services.llm_service import ToolCallRequest, ToolTurn

    turns = iter(
        [
            ToolTurn(
                "",
                [
                    ToolCallRequest(
                        "web",
                        "search_trusted_web",
                        {"query": "attention paper", "reason": "강의자료 부족"},
                    ),
                    ToolCallRequest(
                        "vis",
                        "show_visualization",
                        {
                            "title": "가중치",
                            "kind": "formula",
                            "caption": "비율로 바꿔요.",
                            "latex": "a/(a+b)",
                            "labels": [],
                            "points": [],
                            "x_label": "",
                            "y_label": "",
                        },
                    ),
                ],
                "test",
            ),
            ToolTurn("소프트맥스는 점수를 확률처럼 바꿔요. 왜 나눌까요?", [], "test"),
        ]
    )

    class FakeLLM:
        async def stream_tool_turn(self, **kwargs):
            if kwargs.get("on_reasoning"):
                await kwargs["on_reasoning"]("근거를 확인한다.")
            return next(turns)

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    monkeypatch.setattr(brain, "LLMService", lambda *_args, **_kwargs: FakeLLM())
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )
    async def slow_web_search(*_args, **_kwargs) -> str:
        import asyncio

        await asyncio.sleep(0.05)
        return json.dumps({"found": True, "sources": ["https://arxiv.org/a"]})

    monkeypatch.setattr(brain, "search_trusted_web", slow_web_search)

    reply, tools, sources, visuals = await brain.think(
        context, "소프트맥스가 뭐야?", brain.StageTimer(), on_event=on_event
    )

    assert "확률" in reply and sources == ["https://arxiv.org/a"] and visuals
    final = steps(events)
    assert final["llm-1"]["label"] == "도구 2개를 쓰기로 했어요"
    assert final["llm-1"]["detail"] == "search_trusted_web, show_visualization"
    assert final["tool-1-0"]["stage"] == "search_trusted_web"
    assert final["tool-1-0"]["label"] == "웹 출처 1개를 찾았어요"
    assert final["tool-1-1"]["label"] == "수식을 준비했어요"
    assert final["tool-1-1"]["detail"] == "가중치"
    assert final["llm-2"]["label"] == "답변을 정리했어요"
    running_labels = [e["label"] for e in events if e["type"] == "step" and e["state"] == "running"]
    assert "신뢰할 수 있는 웹을 검색하는 중" in running_labels
    assert "시각 자료를 그리는 중" in running_labels
    assert [(e["key"], e["text"]) for e in events if e["type"] == "thinking"] == [
        ("llm-1", "근거를 확인한다."), ("llm-2", "근거를 확인한다."),
    ]
    # Each tool line carries its own duration, not the round's.
    assert final["tool-1-0"]["elapsed_ms"] >= 40 > final["tool-1-1"]["elapsed_ms"]


@pytest.mark.asyncio
async def test_a_model_failure_closes_its_step_before_the_turn_fails(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    class FailingLLM:
        async def stream_tool_turn(self, **kwargs):
            raise LLMError("Text LLM Model Server를 사용할 수 없습니다.")

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    monkeypatch.setattr(brain, "LLMService", lambda *_args, **_kwargs: FailingLLM())
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )

    with pytest.raises(LLMError):
        await brain.think(context, "소프트맥스가 뭐야?", brain.StageTimer(), on_event=on_event)

    assert steps(events)["llm-1"] == {
        **steps(events)["llm-1"], "state": "failed", "label": "답을 만들지 못했어요",
    }
    assert "elapsed_ms" in steps(events)["llm-1"]


@pytest.mark.asyncio
async def test_a_truncated_thinking_turn_is_retried_once_without_thinking(monkeypatch) -> None:
    """The reasoning spent the budget; the same turn with thinking off completes, and the
    screen is told to drop whatever had streamed."""
    from unittest.mock import AsyncMock

    from app.services.llm_service import LLMTruncatedError, ToolTurn

    calls: list[dict] = []

    class TruncatingLLM:
        async def stream_tool_turn(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                await kwargs["on_reasoning"]("생각이 아주 길어진다…")
                await kwargs["on_token"]("잘린 ")
                raise LLMTruncatedError("Model output was truncated before completion")
            return ToolTurn("기울기의 반대 방향으로 가요. 왜 그럴까요?", [], "test")

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)
    events: list[dict] = []
    tokens: list[str] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    async def on_token(token: str) -> None:
        tokens.append(token)

    monkeypatch.setattr(brain, "LLMService", lambda *_args, **_kwargs: TruncatingLLM())
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )

    reply, *_ = await brain.think(
        context, "경사하강법이 뭐야?", brain.StageTimer(), on_token=on_token, on_event=on_event
    )

    assert reply == "기울기의 반대 방향으로 가요. 왜 그럴까요?"
    assert [call.get("thinking") for call in calls] == [None, False]
    kinds = [event["type"] for event in events]
    assert "rewind" in kinds
    labels = [e["label"] for e in events if e["type"] == "step" and e["key"] == "llm-1"]
    assert labels == ["답을 구성하는 중", "생각이 길어져 답부터 씁니다", "답변을 정리했어요"]
    # The rewind comes after the truncated tokens and before the retry's step.
    assert kinds.index("rewind") > kinds.index("thinking")
    assert context.history[-1]["content"] == reply


@pytest.mark.asyncio
async def test_a_turn_truncated_even_without_thinking_fails_its_step(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from app.services.llm_service import LLMTruncatedError

    class AlwaysTruncating:
        async def stream_tool_turn(self, **kwargs):
            raise LLMTruncatedError("Model output was truncated before completion")

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    monkeypatch.setattr(brain, "LLMService", lambda *_args, **_kwargs: AlwaysTruncating())
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )

    with pytest.raises(LLMTruncatedError):
        await brain.think(context, "경사하강법이 뭐야?", brain.StageTimer(), on_event=on_event)

    assert steps(events)["llm-1"]["state"] == "failed"
    assert context.history == []


@pytest.mark.asyncio
async def test_a_question_with_nothing_to_search_skips_the_material_step(monkeypatch) -> None:
    from unittest.mock import AsyncMock

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)
    events: list[dict] = []
    searched = []

    async def on_event(event: dict) -> None:
        events.append(event)

    monkeypatch.setattr(brain, "search_course_materials", lambda *args: searched.append(args))
    prefetched = await brain.prefetch_context(context, "네", brain.StageTimer(), on_event=on_event)

    assert searched == []
    assert prefetched["course_materials"] == {"error": brain.NO_QUERY_ERROR}
    material = steps(events)["material"]
    assert material["state"] == "done"
    assert material["label"] == "검색할 내용이 없어 강의자료 검색을 건너뛰었어요"


# --------------------------------------------------------------------------
# Attachments: upload, ask, log, resume
# --------------------------------------------------------------------------


def test_student_attaches_an_image_and_the_agent_reads_it_into_the_turn(
    chat_api, stub_course_search, monkeypatch
) -> None:
    course_id = chat_api.courses["ai"]
    student_id = chat_api.users["student"]
    reset_context(student_id, course_id)
    monkeypatch.setattr(voice_routes, "SessionLocal", chat_api.session_factory)
    # This is the transcript path; the developer's .env may have the direct path on.
    monkeypatch.setattr(app.dependency_overrides[get_settings](), "text_llm_vision", False)

    uploaded = upload(chat_api, "student", "ai", "문제 사진.png", png_bytes(), "image/png")
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    assert attachment["kind"] == "image" and attachment["name"] == "문제 사진.png"
    assert attachment["pages"] == 1 and attachment["size"] == len(png_bytes())

    events = stream(
        chat_api,
        "student",
        "ai",
        {"text": "이 문제 어떻게 접근해?", "attachment_ids": [attachment["id"]]},
    )

    final = steps(events)
    # The file is read before any evidence search, and the student sees it happen.
    order = [e["key"] for e in events if e["type"] == "step" and e["state"] == "running"]
    assert order[:2] == ["attachments", "recall"] or order[:2] == ["attachments", "material"]
    assert final["attachments"]["state"] == "done"
    assert final["attachments"]["label"] == "첨부 파일을 읽었어요"
    assert "이미지 판독 1회" in final["attachments"]["detail"]
    done = events[-1]
    assert done["attachments"][0]["name"] == "문제 사진.png"
    assert done["attachments"][0]["chars"] > 0

    # What the file said is under the question in the model's message and stays
    # (bounded) in the history; the retrieval query saw it too.
    history = get_context(student_id, course_id, "인공지능개론").history
    assert history[0]["role"] == "user"
    assert history[0]["content"].startswith("이 문제 어떻게 접근해?")
    assert attachments.ATTACHMENT_HEADER in history[0]["content"]
    assert "[모의 판독]" in history[0]["content"]
    assert "첨부 내용: [모의 판독]" in stub_course_search[0]
    # The (mock) reply quotes the student's words, not the file block, and says it saw the file.
    assert "'이 문제 어떻게 접근해?'" in done["reply"]
    assert attachments.ATTACHMENT_HEADER not in done["reply"]
    assert "첨부한 파일 1개도 함께 살펴봤어요" in done["reply"]

    with chat_api.session_factory() as session:
        log = session.scalar(select(ChatLog).where(ChatLog.id == done["log_id"]))
        assert log is not None
        # The question column keeps the student's words; the file lives beside it.
        assert log.question == "이 문제 어떻게 접근해?"
        logged = log.retrieval_result["attachments"]
        assert logged[0]["name"] == "문제 사진.png" and "[모의 판독]" in logged[0]["text"]

    # 대화 이력 shows the file without its text …
    detail = chat_api.get(f"/api/chat/sessions/{done['session_id']}", "student").json()
    assert detail["logs"][0]["attachments"] == [
        {"id": attachment["id"], "name": "문제 사진.png", "kind": "image", "pages": 1,
         "size": len(png_bytes())}
    ]

    # … and a reopened conversation gets the text back into the model's history.
    reset_context(student_id, course_id)
    follow_up = chat_api.post(
        f"/api/voice/courses/{course_id}/answer-text",
        "student",
        {"text": "그럼 두 번째 단계는?", "chat_session_id": done["session_id"]},
    )
    assert follow_up.status_code == 200
    restored = get_context(student_id, course_id, "인공지능개론").history
    assert "[모의 판독]" in restored[0]["content"]


def test_attachment_upload_validates_type_content_size_and_pages(chat_api, monkeypatch) -> None:
    rejected = upload(chat_api, "student", "ai", "virus.exe", b"MZ...", "application/octet-stream")
    assert rejected.status_code == 422
    assert "이미지" in rejected.json()["detail"]

    not_an_image = upload(chat_api, "student", "ai", "fake.png", b"not really a png", "image/png")
    assert not_an_image.status_code == 422

    # A decompression bomb is refused from its header, before any pixel is decoded.
    bomb = upload(chat_api, "student", "ai", "bomb.png", png_bytes((9000, 9000)), "image/png")
    assert bomb.status_code == 422
    assert "픽셀" in bomb.json()["detail"]

    not_a_pdf = upload(chat_api, "student", "ai", "fake.pdf", b"hello", "application/pdf")
    assert not_a_pdf.status_code == 422

    empty = upload(chat_api, "student", "ai", "empty.png", b"", "image/png")
    assert empty.status_code == 422

    settings = app.dependency_overrides[get_settings]()
    monkeypatch.setattr(settings, "attachment_max_size_bytes", 100)
    too_big = upload(chat_api, "student", "ai", "big.png", png_bytes((400, 400)), "image/png")
    assert too_big.status_code == 422
    assert "MB" in too_big.json()["detail"]
    monkeypatch.setattr(settings, "attachment_max_size_bytes", 10 * 1024 * 1024)

    monkeypatch.setattr(settings, "attachment_max_pages", 1)
    too_long = upload(
        chat_api, "student", "ai", "long.pdf", text_pdf([[LONG_LINE], [LONG_LINE]]),
        "application/pdf",
    )
    assert too_long.status_code == 422
    assert "1쪽" in too_long.json()["detail"]
    monkeypatch.setattr(settings, "attachment_max_pages", 20)

    # A 40 KB PDF whose one page inflates to 20 MB of text operators would make
    # PDFium spend seconds and gigabytes; it is refused from its stream size.
    bomb = upload(chat_api, "student", "ai", "bomb.pdf", flate_bomb_pdf(), "application/pdf")
    assert bomb.status_code == 422
    assert "복잡" in bomb.json()["detail"]

    # So is a PDF whose embedded image header promises a gigapixel bitmap.
    huge = upload(chat_api, "student", "ai", "huge.pdf", huge_image_pdf(), "application/pdf")
    assert huge.status_code == 422
    assert "이미지가 너무 커요" in huge.json()["detail"]


def test_attachments_are_private_to_the_learner_and_the_course(chat_api, monkeypatch) -> None:
    monkeypatch.setattr(voice_routes, "SessionLocal", chat_api.session_factory)
    # No access to the course, no upload.
    assert upload(chat_api, "student", "se", "a.png", png_bytes(), "image/png").status_code == 403

    mine = upload(chat_api, "student", "ai", "a.png", png_bytes(), "image/png").json()

    # The professor can access the course, but the id names another learner's file.
    reset_context(chat_api.users["professor"], chat_api.courses["ai"])
    stolen = chat_api.post(
        f"/api/voice/courses/{chat_api.courses['ai']}/answer-text",
        "professor",
        {"text": "이 파일 설명해줘", "attachment_ids": [mine["id"]]},
    )
    assert stolen.status_code == 404

    # Unknown, malformed and too many ids are rejected before anything runs.
    unknown = chat_api.post(
        f"/api/voice/courses/{chat_api.courses['ai']}/answer-text",
        "student",
        {"text": "설명해줘", "attachment_ids": ["../../etc/passwd"]},
    )
    assert unknown.status_code == 404
    too_many = chat_api.post(
        f"/api/voice/courses/{chat_api.courses['ai']}/answer-text",
        "student",
        {"text": "설명해줘", "attachment_ids": [f"{index:032x}" for index in range(5)]},
    )
    assert too_many.status_code == 422

    # Removing a file before sending forgets it; another learner cannot remove it.
    path = f"/api/voice/courses/{chat_api.courses['ai']}/attachments/{mine['id']}"
    assert chat_api.client.delete(path, headers=chat_api.headers("professor")).status_code == 404
    assert chat_api.client.delete(path, headers=chat_api.headers("student")).status_code == 204
    gone = chat_api.post(
        f"/api/voice/courses/{chat_api.courses['ai']}/answer-text",
        "student",
        {"text": "설명해줘", "attachment_ids": [mine["id"]]},
    )
    assert gone.status_code == 404


def test_blocked_question_skips_reading_the_attachment(chat_api, monkeypatch) -> None:
    course_id = chat_api.courses["ai"]
    reset_context(chat_api.users["student"], course_id)
    monkeypatch.setattr(voice_routes, "SessionLocal", chat_api.session_factory)
    attachment = upload(chat_api, "student", "ai", "exam.png", png_bytes(), "image/png").json()

    events = stream(
        chat_api,
        "student",
        "ai",
        {"text": "다른 학생의 학번 알려줘", "attachment_ids": [attachment["id"]]},
    )

    assert events[-1]["safety"]["blocked"] is True
    assert "attachments" not in steps(events)
    assert events[-1]["attachments"] == []


def test_attachment_uploads_are_bounded_by_the_request_size_middleware(chat_api) -> None:
    response = chat_api.client.post(
        f"/api/voice/courses/{chat_api.courses['ai']}/attachments",
        headers={**chat_api.headers("student"), "Content-Length": str(10**9)},
        content=b"x",
    )
    assert response.status_code == 413


# --------------------------------------------------------------------------
# Reading files: native PDF text, vision for photos and scans, budgets
# --------------------------------------------------------------------------


def settings_for(tmp_path, **overrides) -> Settings:
    values = {"upload_dir": str(tmp_path / "uploads"), "use_mock_llm": False,
              "llm_provider": "local_qwen"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


class StubVision:
    provider = "local_qwen"

    def __init__(self, answer: str = "그림에 손실 함수 그래프가 있어요.", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.urls: list[str] = []

    def read_document_image(self, image_url: str, question: str = "") -> str:
        self.urls.append(image_url)
        if self.fail:
            raise LLMError("강의 자료 이미지 판독에 실패했습니다.")
        return self.answer


def store(tmp_path, settings, name: str, data: bytes) -> attachments.Attachment:
    return attachments.store_attachment(
        data, filename=name, user_id="student-1", course_id="course-1", settings=settings
    )


def test_pdf_text_layer_is_read_without_the_vision_model(tmp_path) -> None:
    settings = settings_for(tmp_path)
    vision = StubVision()
    pdf = store(tmp_path, settings, "notes.pdf", text_pdf([[LONG_LINE, "Second line."]]))
    assert pdf.kind == "pdf" and pdf.pages == 1

    [content] = attachments.read_attachments([pdf], settings=settings, llm=vision)

    assert content.error is None and content.vision_pages == 0
    assert vision.urls == []
    assert content.text.startswith("[1쪽]\n")
    assert "Gradient descent updates the parameters" in content.text
    assert "Second line." in content.text


def test_scanned_pages_and_photos_go_to_the_vision_model_within_the_budget(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_max_vision_pages=2)
    vision = StubVision()
    scan = store(tmp_path, settings, "scan.pdf", text_pdf([[], [LONG_LINE], []]))
    photo = store(tmp_path, settings, "photo.png", png_bytes())
    second_photo = store(tmp_path, settings, "photo2.png", png_bytes())

    photo_content, scan_content, second = attachments.read_attachments(
        [photo, scan, second_photo], settings=settings, llm=vision
    )

    # The photo takes one vision read. In the scan, page 1 is blank and takes
    # the other; page 2 has a text layer and costs nothing; page 3 is blank but
    # the budget is spent, so it is listed as skipped -- never written into the
    # text, where a page count or the retrieval query would take it for content.
    assert scan_content.vision_pages == 1
    assert "[1쪽]\n그림에 손실 함수 그래프가 있어요." in scan_content.text
    assert "[2쪽]\nGradient descent" in scan_content.text
    assert "[3쪽]" not in scan_content.text and "건너" not in scan_content.text
    assert scan_content.skipped_pages == [3] and scan_content.error is None
    assert photo_content.vision_pages == 1 and photo_content.text == vision.answer
    assert second.text == "" and "한도" in (second.error or "")
    assert len(vision.urls) == 2
    assert all(url.startswith("data:image/jpeg;base64,") for url in vision.urls)
    block = attachments.attachment_block([scan_content])
    assert "3쪽은 글자가 없어 건너뛰었어요" in block
    assert attachments.read_label([scan_content]) == ("첨부 파일을 읽었어요", "3쪽 · 이미지 판독 1회 · 1쪽 건너뜀")
    hint = attachments.retrieval_hint([scan_content])
    assert "[1쪽]" not in hint and hint.startswith("그림에 손실 함수 그래프가 있어요. Gradient descent")


def test_a_scan_with_no_vision_budget_is_reported_as_unread(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_max_vision_pages=0)
    scan = store(tmp_path, settings, "scan.pdf", text_pdf([[], []]))

    [content] = attachments.read_attachments([scan], settings=settings, llm=StubVision())

    assert content.text == "" and content.skipped_pages == [1, 2]
    assert content.error and "한도" in content.error
    assert attachments.read_label([content])[0] == "첨부 파일을 읽지 못했어요"
    assert attachments.retrieval_hint([content]) == ""
    assert "(읽지 못함:" in attachments.model_content("이거 뭐야?", [content])


def test_a_vision_failure_records_the_error_instead_of_failing_the_turn(tmp_path) -> None:
    settings = settings_for(tmp_path)
    photo = store(tmp_path, settings, "photo.jpg", png_bytes())

    [content] = attachments.read_attachments(
        [photo], settings=settings, llm=StubVision(fail=True)
    )

    assert content.text == "" and content.error == "강의 자료 이미지 판독에 실패했습니다."
    block = attachments.model_content("이거 뭐야?", [content])
    assert "(읽지 못함: 강의 자료 이미지 판독에 실패했습니다.)" in block
    label, detail = attachments.read_label([content])
    assert label == "첨부 파일을 읽지 못했어요"
    assert detail == "강의 자료 이미지 판독에 실패했습니다."


def test_text_budgets_bound_the_turn_and_the_history_separately(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_max_chars=1000, attachment_history_chars=300)
    content = attachments.AttachmentContent(
        id="a", name="long.pdf", kind="pdf", pages=3, text="가" * 900, size=10
    )

    full = attachments.model_content("요약해줘", [content])
    kept = attachments.history_content("요약해줘", [content], settings=settings)

    assert full.startswith("요약해줘\n\n" + attachments.ATTACHMENT_HEADER)
    assert "### long.pdf (PDF, 3쪽)" in full and "가" * 900 in full
    assert len(kept) < len(full)
    assert "가" * 300 not in kept and attachments.TRUNCATED_MARK in kept
    assert "일부만 실려 있음" in kept
    # The retrieval hint is a short, whitespace-collapsed excerpt.
    assert len(attachments.retrieval_hint([content])) == 400
    assert attachments.retrieval_hint([]) == ""


def test_per_file_budget_clips_a_long_pdf_and_says_so(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_max_chars=1600)
    pdf = store(tmp_path, settings, "long.pdf", text_pdf([[LONG_LINE] * 8, [LONG_LINE] * 8]))

    content, _second = attachments.read_attachments(
        [pdf, pdf], settings=settings, llm=StubVision()
    )

    assert content.truncated is True
    assert len(content.text) <= 820
    assert attachments.TRUNCATED_MARK in content.text


def test_logged_records_round_trip_into_history_content(tmp_path) -> None:
    settings = settings_for(tmp_path)
    content = attachments.AttachmentContent(
        id="a", name="p.png", kind="image", pages=1, text="x = 3", size=5, vision_pages=1
    )
    logged = attachments.logged_list([content])
    assert logged[0]["text"] == "x = 3" and logged[0]["chars"] == 5
    assert attachments.wire_list([content])[0] == {
        "id": "a", "name": "p.png", "kind": "image", "size": 5, "pages": 1, "chars": 5,
        "mode": "inline", "pages_used": [],
    }
    restored = attachments.from_logged(logged)
    assert restored[0].text == "x = 3" and restored[0].kind == "image"
    assert attachments.from_logged("nonsense") == []
    assert "x = 3" in attachments.history_content("뭐야", restored, settings=settings)


def test_load_attachment_checks_ownership_and_ignores_bad_ids(tmp_path) -> None:
    settings = settings_for(tmp_path)
    stored = store(tmp_path, settings, "a.png", png_bytes())

    assert attachments.load_attachment(
        stored.id, user_id="student-1", course_id="course-1", settings=settings
    ) == stored
    assert attachments.load_attachment(
        stored.id, user_id="student-1", course_id="course-2", settings=settings
    ) is None
    assert attachments.load_attachment(
        stored.id, user_id="student-2", course_id="course-1", settings=settings
    ) is None
    assert attachments.load_attachment(
        "../" + stored.id, user_id="student-1", course_id="course-1", settings=settings
    ) is None
    attachments.delete_attachment(stored)
    assert attachments.load_attachment(
        stored.id, user_id="student-1", course_id="course-1", settings=settings
    ) is None


def test_storage_is_bounded_per_learner_oldest_first(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_max_stored_files=2)
    first = store(tmp_path, settings, "a.png", png_bytes())
    second = store(tmp_path, settings, "b.png", png_bytes())
    third = store(tmp_path, settings, "c.png", png_bytes())

    def loaded(item):
        return attachments.load_attachment(
            item.id, user_id="student-1", course_id="course-1", settings=settings
        )

    assert loaded(first) is None
    assert loaded(second) is not None and loaded(third) is not None
    assert len(list(attachments.attachment_dir("student-1", settings).glob("*.json"))) == 2

    tight = settings_for(tmp_path, attachment_max_stored_bytes=len(png_bytes()) + 10)
    fourth = store(tmp_path, tight, "d.png", png_bytes())
    remaining = list(attachments.attachment_dir("student-1", tight).glob("*.json"))
    assert [path.name.split(".")[0] for path in remaining] == [fourth.id]


def test_load_attachment_uses_where_the_sidecar_is_not_the_recorded_path(tmp_path) -> None:
    settings = settings_for(tmp_path)
    stored = store(tmp_path, settings, "a.png", png_bytes())
    sidecar = Path(stored.path + ".json")
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    record["path"] = "/moved/elsewhere/" + Path(stored.path).name
    sidecar.write_text(json.dumps(record), encoding="utf-8")

    loaded = attachments.load_attachment(
        stored.id, user_id="student-1", course_id="course-1", settings=settings
    )

    assert loaded is not None and loaded.path == stored.path
    attachments.delete_attachment(loaded)
    assert not Path(stored.path).exists() and not sidecar.exists()


def test_older_turns_keep_only_the_file_names_when_the_model_is_called(tmp_path) -> None:
    settings = settings_for(tmp_path)
    content = attachments.AttachmentContent("a", "notes.pdf", "pdf", 2, "가" * 300, size=1)
    turn = attachments.history_content("요약해줘", [content], settings=settings)
    history = [
        {"role": "user", "content": turn},
        {"role": "assistant", "content": "첫 답"},
        {"role": "user", "content": turn.replace("요약해줘", "다시 설명해줘")},
        {"role": "assistant", "content": "둘째 답"},
        {"role": "user", "content": "그냥 질문"},
        {"role": "assistant", "content": "셋째 답"},
        {"role": "user", "content": turn.replace("요약해줘", "이번엔?")},
    ]

    collapsed = attachments.collapse_old_attachments(history, keep=2)

    assert "가" * 300 not in collapsed[0]["content"]
    assert collapsed[0]["content"].startswith("요약해줘\n\n" + attachments.ATTACHMENT_HEADER)
    assert "### notes.pdf (PDF, 2쪽)" in collapsed[0]["content"]
    assert attachments.ELIDED_MARK in collapsed[0]["content"]
    assert "가" * 300 in collapsed[2]["content"] and "가" * 300 in collapsed[6]["content"]
    assert collapsed[4] == history[4] and collapsed[1] == history[1]
    # A message without attachments is returned untouched.
    assert attachments.summarize_attachment_block("그냥 질문") == "그냥 질문"


def test_reading_labels_summarize_the_turns_files() -> None:
    running = attachments.reading_label(
        [SimpleNamespace(name="a.pdf"), SimpleNamespace(name="b.png")]  # type: ignore[list-item]
    )
    assert running == ("첨부 파일 2개를 읽는 중", "a.pdf, b.png")
    pdf = attachments.AttachmentContent("1", "a.pdf", "pdf", 3, "text", skipped_pages=[3])
    photo = attachments.AttachmentContent("2", "b.png", "image", 1, "text", vision_pages=1)
    failed = attachments.AttachmentContent("3", "c.png", "image", 1, "", error="x")
    assert attachments.read_label([pdf, photo, failed]) == (
        "첨부 파일 2개를 읽었어요", "4쪽 · 이미지 판독 1회 · 1쪽 건너뜀 · 1개는 읽지 못함"
    )
    # Page lists survive the log round trip.
    restored = attachments.from_logged(attachments.logged_list([pdf]))[0]
    assert restored.skipped_pages == [3]
