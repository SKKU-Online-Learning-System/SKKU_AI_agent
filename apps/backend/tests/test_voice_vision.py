"""With the text model's vision on, an attached image rides in the message itself."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.api.routes import voice as voice_routes
from app.core.config import Settings, get_settings
from app.main import app
from app.services import llm_service
from app.services.llm_service import LLMBadRequestError, LLMService, ToolTurn
from app.services.voice import attachments, brain, external_brain, trusted_sites
from app.services.voice.session_store import get_context, reset_context
from test_local_qwen_provider import FakeAsyncClient
from test_voice_attachments import StubVision, png_bytes, stream, text_pdf, upload

VISION_SETTINGS = Settings(_env_file=None, use_mock_llm=True, text_llm_vision=True)


@pytest.fixture(autouse=True)
def isolated_voice_state(tmp_path, monkeypatch):
    monkeypatch.setattr(trusted_sites, "voice_storage_dir", lambda: tmp_path / "voice")
    monkeypatch.setattr(external_brain, "get_settings", lambda: VISION_SETTINGS)
    monkeypatch.setattr(brain, "get_settings", lambda: VISION_SETTINGS)


def settings_for(tmp_path, **overrides) -> Settings:
    values = {"upload_dir": str(tmp_path / "uploads"), "use_mock_llm": False,
              "llm_provider": "local_qwen", "text_llm_vision": True}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def store(settings, name: str, data: bytes) -> attachments.Attachment:
    return attachments.store_attachment(
        data, filename=name, user_id="student-1", course_id="course-1", settings=settings
    )


IMAGE_PART = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/AAA="}}


# --------------------------------------------------------------------------
# The provider boundary carries images and names a refusal
# --------------------------------------------------------------------------


def test_user_messages_keep_their_image_parts_for_qwen_and_anthropic() -> None:
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "이 그림 뭐야?"}, IMAGE_PART]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                      "content": "{}"}]},
    ]

    canonical = llm_service._ensure_openai_messages(messages)
    assert canonical[0]["content"] == [{"type": "text", "text": "이 그림 뭐야?"}, IMAGE_PART]
    assert canonical[1]["role"] == "tool"

    converted = llm_service._openai_messages_to_anthropic(canonical[:1])
    assert converted[0]["content"][0] == {"type": "text", "text": "이 그림 뭐야?"}
    assert converted[0]["content"][1]["source"] == {
        "type": "base64", "media_type": "image/jpeg", "data": "/9j/AAA=",
    }
    # The mock still finds the student's words inside a parts list.
    assert llm_service._last_user_text(canonical) == "이 그림 뭐야?"


@pytest.mark.asyncio
async def test_a_400_from_the_model_server_is_a_bad_request_not_an_outage(monkeypatch) -> None:
    class RefusingResponse:
        status_code = 400

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def aread(self):
            return b'{"error":"image input is not supported by a language-only model"}'

        def raise_for_status(self):
            raise AssertionError("not reached")

        async def aiter_lines(self):
            yield "data: [DONE]"

    class RefusingClient(FakeAsyncClient):
        def stream(self, method, path, *, json):
            self.stream_requests.append({"json": json})
            return RefusingResponse()

    monkeypatch.setattr(llm_service, "async_client", lambda *args: RefusingClient())
    llm = LLMService(Settings(_env_file=None, use_mock_llm=False, llm_provider="local_qwen"))

    with pytest.raises(LLMBadRequestError, match="image input"):
        await llm.stream_tool_turn(
            system="p", messages=[{"role": "user", "content": [IMAGE_PART]}], tools=[]
        )


# --------------------------------------------------------------------------
# Reading: the image itself, within the direct budget, else the transcript
# --------------------------------------------------------------------------


def test_images_ride_directly_within_the_budget_and_transcribe_beyond_it(tmp_path) -> None:
    settings = settings_for(tmp_path, attachment_direct_images_max=1)
    vision = StubVision()
    first = store(settings, "문제.png", png_bytes())
    second = store(settings, "풀이.png", png_bytes())

    direct, transcribed = attachments.read_attachments(
        [first, second], settings=settings, llm=vision
    )

    assert direct.mode == "vision" and direct.text == "" and direct.has_content
    assert direct.images[0]["url"].startswith("data:image/jpeg;base64,")
    assert direct.images[0]["page"] is None
    assert transcribed.mode == "inline" and transcribed.text == vision.answer
    assert vision.urls == [] or len(vision.urls) == 1  # only the second went to the 9B
    parts = attachments.image_parts([direct, transcribed])
    assert len(parts) == 1 and parts[0]["type"] == "image_url"
    block = attachments.model_content("이 문제 어떻게 풀어?", [direct, transcribed])
    assert "### 문제.png (이미지, 메시지에 직접 첨부)\n(내용은 첨부된 이미지를 직접 보고 읽는다)" in block
    assert vision.answer in block
    label, detail = attachments.read_label([direct])
    assert (label, detail) == ("이미지를 모델에 직접 전달했어요", "문제.png")
    # The record never carries the image bytes; the mode survives the log.
    logged = attachments.logged_list([direct])[0]
    assert "images" not in logged and logged["mode"] == "vision"
    assert attachments.from_logged([logged])[0].mode == "vision"


def test_scanned_pdf_pages_ride_as_images_when_the_model_can_see(tmp_path) -> None:
    settings = settings_for(tmp_path)
    scan = store(settings, "scan.pdf", text_pdf([[], []]))

    [content] = attachments.read_attachments([scan], settings=settings, llm=StubVision())

    assert content.mode == "vision" and content.text == ""
    assert [image["page"] for image in content.images] == [1, 2]
    assert "PDF 2쪽, 1, 2쪽은 이미지로 첨부" in attachments.model_content("?", [content])
    assert attachments.read_label([content])[0] == "이미지 2장을 모델에 직접 전달했어요"


def test_with_vision_off_nothing_changes(tmp_path) -> None:
    settings = settings_for(tmp_path, text_llm_vision=False)
    vision = StubVision()
    [content] = attachments.read_attachments(
        [store(settings, "문제.png", png_bytes())], settings=settings, llm=vision
    )
    assert content.mode == "inline" and content.text == vision.answer and not content.images


def test_transcribe_images_turns_the_direct_images_back_into_text(tmp_path) -> None:
    settings = settings_for(tmp_path)
    vision = StubVision()
    [direct] = attachments.read_attachments(
        [store(settings, "문제.png", png_bytes())], settings=settings, llm=vision
    )

    [fallback] = attachments.transcribe_images([direct], llm=vision, settings=settings)

    assert fallback.mode == "inline" and fallback.text == vision.answer and not fallback.images
    assert fallback.vision_pages == 1
    assert len(vision.urls) == 1


# --------------------------------------------------------------------------
# The brain: images in the message, carried one turn, transcript on refusal
# --------------------------------------------------------------------------


def make_context() -> brain.VoiceContext:
    memory = AsyncMock()
    memory.all_memories.return_value = []
    return brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)


def vision_content(name: str, url: str) -> attachments.AttachmentContent:
    return attachments.AttachmentContent(
        name, name, "image", 1, "", size=1, mode="vision", images=[{"page": None, "url": url}]
    )


@pytest.mark.asyncio
async def test_the_question_carries_its_images_and_the_next_one_sees_them_once_more(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    class SeeingLLM:
        async def stream_tool_turn(self, **kwargs):
            calls.append(kwargs)
            return ToolTurn("그림의 축을 먼저 볼까요?", [], "test")

    monkeypatch.setattr(brain, "LLMService", lambda *_a, **_k: SeeingLLM())
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )
    context = make_context()
    photo = vision_content("문제.png", "data:image/jpeg;base64,AAAA")

    await brain.think(context, "이 문제 어떻게 풀어?", brain.StageTimer(), attachments=[photo])
    first = calls[-1]["messages"][-1]
    assert first["role"] == "user" and isinstance(first["content"], list)
    assert first["content"][0]["type"] == "text"
    assert first["content"][0]["text"].startswith("이 문제 어떻게 풀어?")
    assert first["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}
    # The history keeps words only; the image is remembered for one more turn.
    assert isinstance(context.history[0]["content"], str)
    assert "(이미지, 메시지에 직접 첨부)" in context.history[0]["content"]
    assert context.recent_images == [first["content"][1]]

    await brain.think(context, "그럼 2번은?", brain.StageTimer())
    second = calls[-1]["messages"][-1]
    assert isinstance(second["content"], list)
    assert second["content"][1]["image_url"]["url"] == "data:image/jpeg;base64,AAAA"
    assert context.recent_images == []

    await brain.think(context, "고마워", brain.StageTimer())
    assert isinstance(calls[-1]["messages"][-1]["content"], str)


@pytest.mark.asyncio
async def test_a_text_only_server_gets_the_transcript_instead(monkeypatch) -> None:
    calls: list[dict] = []
    events: list[dict] = []

    class TextOnlyLLM:
        provider = "local_qwen"

        async def stream_tool_turn(self, **kwargs):
            calls.append(kwargs)
            if isinstance(kwargs["messages"][-1]["content"], list):
                raise LLMBadRequestError("Text LLM이 요청을 거절했습니다: image input")
            return ToolTurn("축부터 볼까요?", [], "test")

        def read_document_image(self, url, question=""):
            return "그래프에 x축 학습률, y축 손실이 있다."

    async def on_event(event):
        events.append(event)

    monkeypatch.setattr(brain, "LLMService", lambda *_a, **_k: TextOnlyLLM())
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )
    context = make_context()
    photo = vision_content("문제.png", "data:image/jpeg;base64,AAAA")

    reply, *_ = await brain.think(
        context, "이 그래프 뭐야?", brain.StageTimer(), on_event=on_event, attachments=[photo]
    )

    assert reply == "축부터 볼까요?"
    assert isinstance(calls[0]["messages"][-1]["content"], list)
    retried = calls[1]["messages"][-1]["content"]
    assert isinstance(retried, str) and "그래프에 x축 학습률" in retried
    assert "rewind" in [e["type"] for e in events]
    labels = [e["label"] for e in events if e["type"] == "step" and e["key"] == "llm-1"]
    assert labels[1] == "이미지를 직접 볼 수 없어 글로 옮겨 읽습니다" and labels[-1] == "답변을 정리했어요"
    assert "그래프에 x축 학습률" in context.history[0]["content"]
    assert context.recent_images == []


# --------------------------------------------------------------------------
# Through the API, with a reopened conversation
# --------------------------------------------------------------------------


def test_a_reopened_conversation_reloads_the_photo_for_one_more_turn(chat_api, monkeypatch) -> None:
    course_id = chat_api.courses["ai"]
    student_id = chat_api.users["student"]
    reset_context(student_id, course_id)
    monkeypatch.setattr(voice_routes, "SessionLocal", chat_api.session_factory)
    settings = app.dependency_overrides[get_settings]()
    monkeypatch.setattr(settings, "text_llm_vision", True)
    monkeypatch.setattr(brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), []))
    seen: list[dict] = []
    real = LLMService.stream_tool_turn

    async def spy(self, **kwargs):
        seen.append(kwargs["messages"][-1])
        return await real(self, **kwargs)

    monkeypatch.setattr(LLMService, "stream_tool_turn", spy)

    photo = upload(chat_api, "student", "ai", "문제.png", png_bytes(), "image/png").json()
    events = stream(
        chat_api, "student", "ai", {"text": "이 문제 어떻게 풀어?", "attachment_ids": [photo["id"]]}
    )
    done = events[-1]
    assert done["attachments"][0]["mode"] == "vision"
    assert isinstance(seen[-1]["content"], list) and seen[-1]["content"][1]["type"] == "image_url"
    final = {e["key"]: e for e in events if e["type"] == "step"}
    assert final["attachments"]["label"] == "이미지를 모델에 직접 전달했어요"

    # A reload: the photo comes back from disk with the first follow-up, then no more.
    reset_context(student_id, course_id)
    stream(chat_api, "student", "ai",
           {"text": "그럼 2번은?", "chat_session_id": done["session_id"]})
    assert isinstance(seen[-1]["content"], list)
    assert seen[-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert get_context(student_id, course_id, "인공지능개론").recent_images == []
