import asyncio
import json
from types import SimpleNamespace

import openai
import pytest

from app.core.config import Settings
from app.services import llm_service
from app.services.llm_service import ChatMessage, LLMError, LLMService


def qwen_settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "qwen_api_key": "test-key",
        "qwen_model": "qwen-test",
        "qwen_base_url": "https://qwen.test/compatible-mode/v1",
        "qwen_dashscope_base_url": "https://qwen.test/api/v1",
        "qwen_web_search_model": "qwen-search-test",
        "use_mock_llm": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_qwen_uses_openai_compatible_messages_and_usage(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    client_kwargs: list[dict[str, object]] = []

    class FakeCompletions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                model="qwen-test",
                choices=[SimpleNamespace(message=SimpleNamespace(content="강의자료 기반 답변"))],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=30,
                    total_tokens=130,
                ),
            )

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            client_kwargs.append(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    service = LLMService(qwen_settings())

    response = service.generate_answer(
        [ChatMessage("system", "규칙"), ChatMessage("user", "질문")]
    )

    assert response.answer == "강의자료 기반 답변"
    assert response.model_name == "qwen-test"
    assert response.usage.total_tokens == 130
    assert client_kwargs == [
        {"api_key": "test-key", "base_url": "https://qwen.test/compatible-mode/v1"}
    ]
    assert calls[0]["messages"] == [
        {"role": "system", "content": "규칙"},
        {"role": "user", "content": "질문"},
    ]
    assert calls[0]["temperature"] == 0.2
    assert calls[0]["max_completion_tokens"] == 1024


def test_qwen_requires_api_key() -> None:
    service = LLMService(qwen_settings(qwen_api_key=None))

    with pytest.raises(LLMError, match="QWEN_API_KEY"):
        service.generate_answer([ChatMessage("user", "질문")])


def test_qwen_parses_openai_tool_calls(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeCompletions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                model="qwen-test",
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="show_visualization",
                                        arguments=json.dumps({"kind": "formula"}),
                                    ),
                                )
                            ],
                        )
                    )
                ],
            )

    class FakeClient:
        def __init__(self, **_: object) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    service = LLMService(qwen_settings())
    tools = [
        {
            "type": "function",
            "function": {
                "name": "show_visualization",
                "description": "show it",
                "parameters": {"type": "object"},
            },
        }
    ]

    turn = asyncio.run(service.stream_tool_turn(system="규칙", messages=[], tools=tools))

    assert turn.model_name == "qwen-test"
    assert turn.tool_calls[0].id == "call-1"
    assert turn.tool_calls[0].arguments == {"kind": "formula"}
    assert calls[0]["messages"] == [{"role": "system", "content": "규칙"}]
    assert calls[0]["tools"] == tools
    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["parallel_tool_calls"] is True


def test_qwen_streams_text_and_reassembles_tool_arguments(monkeypatch) -> None:
    chunks = [
        SimpleNamespace(
            model="qwen-test",
            choices=[SimpleNamespace(delta=SimpleNamespace(content="설명", tool_calls=[]))],
        ),
        SimpleNamespace(
            model="qwen-test",
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-stream",
                                function=SimpleNamespace(
                                    name="show_",
                                    arguments='{"kind":',
                                ),
                            )
                        ],
                    )
                )
            ],
        ),
        SimpleNamespace(
            model="qwen-test",
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(
                                    name="visualization",
                                    arguments='"formula"}',
                                ),
                            )
                        ],
                    )
                )
            ],
        ),
    ]

    class FakeStream:
        def __init__(self) -> None:
            self._chunks = iter(chunks)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._chunks)
            except StopIteration as error:
                raise StopAsyncIteration from error

    class FakeCompletions:
        async def create(self, **kwargs: object) -> FakeStream:
            assert kwargs["stream"] is True
            return FakeStream()

    class FakeClient:
        def __init__(self, **_: object) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    streamed: list[str] = []

    async def on_token(token: str) -> None:
        streamed.append(token)

    turn = asyncio.run(
        LLMService(qwen_settings()).stream_tool_turn(
            system="규칙",
            messages=[],
            tools=[],
            on_token=on_token,
        )
    )

    assert streamed == ["설명"]
    assert turn.text == "설명"
    assert turn.tool_calls[0].id == "call-stream"
    assert turn.tool_calls[0].name == "show_visualization"
    assert turn.tool_calls[0].arguments == {"kind": "formula"}


def test_qwen_structured_output_uses_json_mode(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeCompletions:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"save": null, "reviews": []}')
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **_: object) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    result = asyncio.run(
        LLMService(qwen_settings()).generate_json(
            system="JSON 객체만 출력하세요.",
            payload={"conversation": []},
        )
    )

    assert result == {"save": None, "reviews": []}
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["extra_body"] == {"enable_thinking": False}
    assert calls[0]["messages"][0] == {
        "role": "system",
        "content": "JSON 객체만 출력하세요.",
    }


def test_qwen_trusted_search_uses_native_sources_and_allowlist(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            payload = {
                "output": {
                    "choices": [
                        {"message": {"content": [{"text": "공식 문서 기반 답변"}]}}
                    ],
                    "search_info": {
                        "search_results": [
                            {"url": "https://docs.python.org/3/library/asyncio.html"}
                        ]
                    },
                }
            }
            yield f"data: {json.dumps(payload)}"
            yield "data: [DONE]"

    class FakeHttpClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            calls.append({"method": method, "url": url, **kwargs})
            return FakeResponse()

    monkeypatch.setattr(llm_service.httpx, "AsyncClient", FakeHttpClient)
    found = asyncio.run(
        LLMService(qwen_settings()).search_web(
            query="asyncio task",
            system="공식 자료만 사용하세요.",
            allowed_domains=["docs.python.org"],
        )
    )

    assert found.answer == "공식 문서 기반 답변"
    assert found.sources == ["https://docs.python.org/3/library/asyncio.html"]
    assert found.model_name == "qwen-search-test"
    assert calls[0]["url"].endswith("/services/aigc/multimodal-generation/generation")
    request_json = calls[0]["json"]
    assert request_json["model"] == "qwen-search-test"
    assert request_json["parameters"]["search_options"]["enable_source"] is True
