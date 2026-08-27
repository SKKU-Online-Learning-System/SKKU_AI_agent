import json

import httpx
import pytest

from app.core.config import Settings
from app.services import llm_service
from app.services.llm_service import ChatMessage, LLMError, LLMService


class FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://model/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)

    def json(self) -> dict:
        return self.payload


class FakeSyncClient:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.requests: list[dict] = []

    def post(self, path: str, *, json: dict) -> FakeResponse:
        self.requests.append({"path": path, "json": json})
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


class FakeStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class FakeAsyncClient:
    def __init__(self, *, lines: list[str] | None = None, payload: dict | None = None) -> None:
        self.lines = lines or []
        self.payload = payload or {}
        self.stream_requests: list[dict] = []
        self.post_requests: list[dict] = []

    def stream(self, method: str, path: str, *, json: dict) -> FakeStreamResponse:
        self.stream_requests.append({"method": method, "path": path, "json": json})
        return FakeStreamResponse(self.lines)

    async def post(self, path: str, *, json: dict) -> FakeResponse:
        self.post_requests.append({"path": path, "json": json})
        return FakeResponse(self.payload)


def settings(**overrides) -> Settings:
    values = {
        "llm_provider": "local_qwen",
        "use_mock_llm": False,
        "voice_provider": "local_cascade",
        "text_llm_base_url": "http://text:8001/v1",
        "voice_llm_base_url": "http://voice:8002/v1",
        "text_llm_model": "Qwen/Qwen3.8-27B",
        "voice_llm_model": "Qwen/Qwen3.5-9B",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_qwen_generate_answer_uses_text_profile(monkeypatch) -> None:
    fake = FakeSyncClient(
        {
            "model": "Qwen/Qwen3.8-27B",
            "choices": [{"message": {"content": "가상 메모리는 보조 기억장치입니다."}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17},
        }
    )
    monkeypatch.setattr(llm_service, "sync_client", lambda *args: fake)

    response = LLMService(settings(), profile="text").generate_answer(
        [ChatMessage("user", "가상 메모리가 뭐야?")]
    )

    assert response.model_name == "Qwen/Qwen3.8-27B"
    assert response.usage.total_tokens == 17
    assert fake.requests[0]["json"]["model"] == "Qwen/Qwen3.8-27B"
    assert "chat_template_kwargs" not in fake.requests[0]["json"]


def test_qwen_voice_profile_disables_thinking_with_server_contract(monkeypatch) -> None:
    fake = FakeSyncClient(
        {
            "model": "Qwen/Qwen3.5-9B",
            "choices": [{"message": {"content": "짧게 설명할게요."}}],
        }
    )
    monkeypatch.setattr(llm_service, "sync_client", lambda *args: fake)

    LLMService(settings(), profile="voice").generate_answer([ChatMessage("user", "설명해줘")])

    request = fake.requests[0]["json"]
    assert request["model"] == "Qwen/Qwen3.5-9B"
    assert request["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.asyncio
async def test_qwen_streaming_parses_text_and_tool_call_round_trip(monkeypatch) -> None:
    lines = [
        'data: {"model":"Qwen/Qwen3.8-27B","choices":[{"delta":{"content":"확인해볼게요. "}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call-1","function":{"name":"search_course_materials","arguments":"{\\"query\\":\\"가상"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":" 메모리\\"}"}}]}}]}',
        "data: [DONE]",
    ]
    fake = FakeAsyncClient(lines=lines)
    monkeypatch.setattr(llm_service, "async_client", lambda *args: fake)
    tokens: list[str] = []

    turn = await LLMService(settings()).stream_tool_turn(
        system="course policy",
        messages=[
            {"role": "user", "content": "가상 메모리"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "old-call",
                        "type": "function",
                        "function": {"name": "search_course_materials", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "old-call", "content": '{"found":true}'},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_course_materials",
                    "description": "Search course evidence",
                    "parameters": {"type": "object"},
                },
            }
        ],
        on_token=lambda token: _append(tokens, token),
    )

    assert "".join(tokens) == "확인해볼게요. "
    assert turn.tool_calls[0].id == "call-1"
    assert turn.tool_calls[0].name == "search_course_materials"
    assert turn.tool_calls[0].arguments == {"query": "가상 메모리"}
    request_messages = fake.stream_requests[0]["json"]["messages"]
    assert any(message.get("role") == "tool" for message in request_messages)


@pytest.mark.asyncio
async def test_qwen_generate_json_uses_structured_output(monkeypatch) -> None:
    fake = FakeAsyncClient(
        payload={
            "choices": [
                {"message": {"content": json.dumps({"save": None, "reviews": []})}}
            ]
        }
    )
    monkeypatch.setattr(llm_service, "async_client", lambda *args: fake)

    result = await LLMService(settings()).generate_json(system="json only", payload={"x": 1})

    assert result == {"save": None, "reviews": []}
    assert fake.post_requests[0]["json"]["response_format"] == {"type": "json_object"}


def test_model_server_error_is_provider_neutral(monkeypatch) -> None:
    request = httpx.Request("POST", "http://text:8001/v1/chat/completions")
    fake = FakeSyncClient(error=httpx.ConnectError("down", request=request))
    monkeypatch.setattr(llm_service, "sync_client", lambda *args: fake)

    with pytest.raises(LLMError, match="Text LLM Model Server"):
        LLMService(settings()).generate_answer([ChatMessage("user", "hello")])


async def _append(values: list[str], value: str) -> None:
    values.append(value)
