"""Provider-neutral answer generation for the SKKU Course Agent.

The application owns prompts, history and tool execution. This module is the
only LLM provider boundary: local Qwen calls the external Model Server through
its OpenAI-compatible API, while Anthropic remains a legacy regression adapter.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional, Sequence, cast

import httpx

from app.core.config import Settings
from app.services.model_server.client import async_client, sync_client

logger = logging.getLogger(__name__)

MOCK_MODEL_NAME = "mock-llm"
Profile = Literal["text", "voice"]
Provider = Literal["mock", "anthropic", "local_qwen"]


class LLMError(Exception):
    code = "LLM_GENERATION_FAILED"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolTurn:
    text: str
    tool_calls: list[ToolCallRequest]
    model_name: str


@dataclass(frozen=True)
class WebSearchAnswer:
    answer: str
    sources: list[str]
    model_name: str


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


@dataclass(frozen=True)
class LLMResponse:
    answer: str
    model_name: str
    usage: LLMUsage


class LLMService:
    """One stable service boundary for mock, Anthropic and local Qwen."""

    def __init__(self, settings: Settings, profile: Profile = "text") -> None:
        self.settings = settings
        self.profile = profile

    @property
    def provider(self) -> Provider:
        provider = self.settings.effective_llm_provider
        if self.profile == "voice" and self.settings.voice_provider == "local_cascade":
            return "mock" if self.settings.use_mock_llm else "local_qwen"
        return provider

    @property
    def model_name(self) -> str:
        if self.provider == "mock":
            return MOCK_MODEL_NAME
        if self.provider == "anthropic":
            return self.settings.claude_model
        return self.settings.voice_llm_model if self.profile == "voice" else self.settings.text_llm_model

    @property
    def base_url(self) -> str:
        return self.settings.voice_llm_base_url if self.profile == "voice" else self.settings.text_llm_base_url

    def generate_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        if not messages:
            raise LLMError("생성할 메시지가 없습니다.")
        logger.info(
            "llm request provider=%s model=%s profile=%s messages=%d prompt_chars=%d",
            self.provider,
            self.model_name,
            self.profile,
            len(messages),
            sum(len(message.content) for message in messages),
        )
        if self.provider == "mock":
            return LLMResponse(_mock_answer(messages), MOCK_MODEL_NAME, LLMUsage())
        if self.provider == "anthropic":
            return self._anthropic_answer(messages)
        return self._qwen_answer(messages)

    def _qwen_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        request = self._qwen_request(
            messages=[{"role": message.role, "content": message.content} for message in messages],
            stream=False,
        )
        try:
            client = sync_client(
                self.base_url,
                self.settings.model_server_api_key,
                self.settings.model_request_timeout_seconds,
            )
            response = client.post("chat/completions", json=request)
            response.raise_for_status()
            payload = response.json()
            answer = str(payload["choices"][0]["message"].get("content") or "").strip()
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise self._model_server_error() from exc
        if not answer:
            raise LLMError(f"{self._profile_label()}이 빈 답변을 반환했습니다.")
        return LLMResponse(
            answer=answer,
            model_name=str(payload.get("model") or self.model_name),
            usage=_openai_usage(payload.get("usage")),
        )

    def _anthropic_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        if not self.settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        try:
            from anthropic import Anthropic
            from anthropic.types import MessageParam

            system = "\n\n".join(message.content for message in messages if message.role == "system")
            provider_messages: list[MessageParam] = [
                {
                    "role": cast(Literal["user", "assistant"], message.role),
                    "content": message.content,
                }
                for message in messages
                if message.role != "system"
            ]
            response = Anthropic(api_key=self.settings.anthropic_api_key).messages.create(
                model=self.settings.claude_model,
                max_tokens=self.settings.llm_max_tokens,
                messages=provider_messages,
                system=system,
            )
        except Exception as exc:
            raise LLMError("Claude 답변 생성에 실패했습니다.") from exc

        answer = "".join(block.text for block in response.content if block.type == "text").strip()
        if not answer:
            raise LLMError("Claude가 빈 답변을 반환했습니다.")
        prompt_tokens = getattr(response.usage, "input_tokens", None)
        completion_tokens = getattr(response.usage, "output_tokens", None)
        return LLMResponse(
            answer=answer,
            model_name=response.model,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=(
                    prompt_tokens + completion_tokens
                    if prompt_tokens is not None and completion_tokens is not None
                    else None
                ),
            ),
        )

    def _require_anthropic_client(self):
        if not self.settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=self.settings.anthropic_api_key)

    async def stream_tool_turn(
        self,
        *,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
        force_tools: Sequence[str] = (),
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_call_started: Optional[Callable[[], Awaitable[None]]] = None,
        max_tokens: Optional[int] = None,
    ) -> ToolTurn:
        """Run one tool turn with OpenAI function shape as the canonical form.

        Older Anthropic-shaped history from the pre-migration brain is accepted
        only as an input compatibility format and normalized here, rather than
        leaking provider conversion into new code.
        """
        canonical_messages = _ensure_openai_messages(messages)
        canonical_tools = _ensure_openai_tools(tools)
        if self.provider == "mock":
            turn = _mock_tool_turn(
                canonical_messages,
                canonical_tools,
                force_tools,
                system=system,
            )
            if on_token and turn.text:
                await on_token(turn.text)
            if turn.tool_calls and on_tool_call_started:
                await on_tool_call_started()
            return turn
        if self.provider == "anthropic":
            return await self._anthropic_tool_turn(
                system=system,
                messages=canonical_messages,
                tools=canonical_tools,
                force_tools=force_tools,
                on_token=on_token,
                on_tool_call_started=on_tool_call_started,
                max_tokens=max_tokens,
            )
        return await self._qwen_tool_turn(
            system=system,
            messages=canonical_messages,
            tools=canonical_tools,
            force_tools=force_tools,
            on_token=on_token,
            on_tool_call_started=on_tool_call_started,
            max_tokens=max_tokens,
        )

    async def _qwen_tool_turn(
        self,
        *,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
        force_tools: Sequence[str],
        on_token: Optional[Callable[[str], Awaitable[None]]],
        on_tool_call_started: Optional[Callable[[], Awaitable[None]]],
        max_tokens: Optional[int],
    ) -> ToolTurn:
        request = self._qwen_request(
            messages=[{"role": "system", "content": system}, *list(messages)],
            stream=True,
            max_tokens=max_tokens,
        )
        if tools:
            request["tools"] = list(tools)
            request["tool_choice"] = "required" if force_tools else "auto"

        text_parts: list[str] = []
        tool_parts: dict[int, dict[str, str]] = {}
        returned_model = self.model_name
        try:
            client = async_client(
                self.base_url,
                self.settings.model_server_api_key,
                self.settings.model_request_timeout_seconds,
            )
            async with client.stream("POST", "chat/completions", json=request) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    if not raw:
                        continue
                    chunk = json.loads(raw)
                    returned_model = str(chunk.get("model") or returned_model)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        text = str(text)
                        text_parts.append(text)
                        if on_token:
                            await on_token(text)
                    for item in delta.get("tool_calls") or []:
                        if not tool_parts and on_tool_call_started:
                            # The round is producing a tool call, so any content
                            # streamed above is preamble that will not survive into
                            # the final reply. Let callers stop speaking it.
                            await on_tool_call_started()
                        index = int(item.get("index", 0))
                        current = tool_parts.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        if item.get("id"):
                            current["id"] += str(item["id"])
                        function = item.get("function") or {}
                        if function.get("name"):
                            current["name"] += str(function["name"])
                        if function.get("arguments"):
                            current["arguments"] += str(function["arguments"])
        except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise self._model_server_error() from exc

        tool_calls = [
            ToolCallRequest(
                id=value["id"] or f"tool-{index}",
                name=value["name"],
                arguments=_parse_tool_arguments(value["arguments"]),
            )
            for index, value in sorted(tool_parts.items())
            if value["name"]
        ]
        return ToolTurn("".join(text_parts), tool_calls, returned_model)

    async def _anthropic_tool_turn(
        self,
        *,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
        force_tools: Sequence[str],
        on_token: Optional[Callable[[str], Awaitable[None]]],
        on_tool_call_started: Optional[Callable[[], Awaitable[None]]],
        max_tokens: Optional[int],
    ) -> ToolTurn:
        client = self._require_anthropic_client()
        request = {
            "model": self.settings.claude_model,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "system": system,
            "messages": _openai_messages_to_anthropic(messages),
            "tools": _openai_tools_to_anthropic(tools),
            "tool_choice": {"type": "any"} if force_tools else {"type": "auto"},
        }
        try:
            if on_token is None:
                message = await client.messages.create(**request)
            else:
                seen_tool_use = False
                async with client.messages.stream(**request) as stream:
                    async for event in stream:
                        if event.type == "text" and event.text:
                            await on_token(event.text)
                        elif (
                            not seen_tool_use
                            and on_tool_call_started
                            and event.type == "content_block_start"
                            and getattr(event.content_block, "type", None) == "tool_use"
                        ):
                            seen_tool_use = True
                            await on_tool_call_started()
                    message = await stream.get_final_message()
        except Exception as exc:
            raise LLMError("Claude 답변 생성에 실패했습니다.") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                arguments = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(ToolCallRequest(block.id, block.name, arguments))
        return ToolTurn("".join(text_parts), tool_calls, message.model)

    async def generate_json(self, *, system: str, payload: dict, max_tokens: int = 900) -> dict:
        if self.provider == "mock":
            return {"save": None, "reviews": []}
        if self.provider == "anthropic":
            return await self._anthropic_generate_json(system, payload, max_tokens)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        last_error: Exception | None = None
        for structured in (True, False):
            request = self._qwen_request(messages=messages, stream=False, max_tokens=max_tokens)
            if structured:
                request["response_format"] = {"type": "json_object"}
            else:
                request["messages"] = [
                    *messages,
                    {"role": "user", "content": "Return exactly one valid JSON object and no markdown fence."},
                ]
            try:
                client = async_client(
                    self.base_url,
                    self.settings.model_server_api_key,
                    self.settings.model_request_timeout_seconds,
                )
                response = await client.post("chat/completions", json=request)
                response.raise_for_status()
                raw = str(response.json()["choices"][0]["message"].get("content") or "")
                return _parse_json_object(raw)
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
        raise LLMError("구조화 JSON 생성에 실패했습니다.") from last_error

    async def _anthropic_generate_json(self, system: str, payload: dict, max_tokens: int) -> dict:
        client = self._require_anthropic_client()
        try:
            message = await client.messages.create(
                model=self.settings.claude_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            raw = "".join(block.text for block in message.content if block.type == "text").strip()
            return _parse_json_object(raw)
        except Exception as exc:
            raise LLMError("구조화 JSON 생성에 실패했습니다.") from exc

    async def search_web(
        self,
        *,
        query: str,
        system: str = "",
        allowed_domains: Sequence[str],
    ) -> WebSearchAnswer:
        """Compatibility facade backed by application-owned SearXNG.

        Claude's server-side web_search tool is deliberately not used. The
        returned snippets become evidence in the caller's next Qwen/Claude turn.
        """
        from app.services.trusted_web_search import TrustedWebSearchError, TrustedWebSearchService

        try:
            results = await TrustedWebSearchService(self.settings).search(query, list(allowed_domains))
        except TrustedWebSearchError as exc:
            raise LLMError(str(exc)) from exc
        if not results:
            raise LLMError("신뢰 도메인에서 충분한 검색 근거를 찾지 못했습니다.")
        evidence = "\n\n".join(
            f"[{index}] {result.title}\n{result.snippet}"
            for index, result in enumerate(results, start=1)
        )
        return WebSearchAnswer(
            answer=evidence,
            sources=[result.url for result in results],
            model_name="searxng",
        )

    def _qwen_request(
        self,
        *,
        messages: Sequence[dict],
        stream: bool,
        max_tokens: int | None = None,
    ) -> dict:
        request = {
            "model": self.model_name,
            "messages": list(messages),
            "stream": stream,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "temperature": self.settings.llm_temperature,
        }
        if self.profile == "voice":
            request["chat_template_kwargs"] = {"enable_thinking": False}
        return request

    def _profile_label(self) -> str:
        return "Voice LLM" if self.profile == "voice" else "Text LLM"

    def _model_server_error(self) -> LLMError:
        return LLMError(f"{self._profile_label()} Model Server를 사용할 수 없습니다.")


def _ensure_openai_tools(tools: Sequence[dict]) -> list[dict]:
    canonical: list[dict] = []
    for tool in tools:
        function = tool.get("function")
        if tool.get("type") == "function" and isinstance(function, dict):
            canonical.append(dict(tool))
            continue
        # Old Anthropic shape: {name, description, input_schema}.
        if tool.get("name") and tool.get("input_schema"):
            canonical.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object"}),
                    },
                }
            )
            continue
        # xAI realtime-style compatibility: {type:function,name,parameters}.
        if tool.get("type") == "function" and tool.get("name"):
            canonical.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object"}),
                    },
                }
            )
    return canonical


def _ensure_openai_messages(messages: Sequence[dict]) -> list[dict]:
    canonical: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "assistant" and isinstance(content, list):
            text = "".join(
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            calls = []
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                calls.append(
                    {
                        "id": str(block.get("id") or ""),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name") or ""),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    }
                )
            entry = {"role": "assistant", "content": text}
            if calls:
                entry["tool_calls"] = calls
            canonical.append(entry)
            continue
        if role == "user" and isinstance(content, list):
            text_parts = [
                str(block.get("text") or "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            if any(text_parts):
                canonical.append({"role": "user", "content": "".join(text_parts)})
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                canonical.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(block.get("tool_use_id") or ""),
                        "content": str(block.get("content") or ""),
                    }
                )
            continue
        if role in {"user", "assistant", "system", "tool"}:
            canonical.append(dict(message))
    return canonical


def _openai_tools_to_anthropic(tools: Sequence[dict]) -> list[dict]:
    converted: list[dict] = []
    for tool in tools:
        function = tool.get("function") or {}
        if tool.get("type") != "function" or not function.get("name"):
            continue
        converted.append(
            {
                "name": function["name"],
                "description": function.get("description", ""),
                "input_schema": function.get("parameters", {"type": "object"}),
            }
        )
    return converted


def _openai_messages_to_anthropic(messages: Sequence[dict]) -> list[dict]:
    converted: list[dict] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": str(message.get("tool_call_id", "")),
                "content": str(message.get("content", "")),
            }
            if (
                converted
                and converted[-1].get("role") == "user"
                and isinstance(converted[-1].get("content"), list)
                and all(
                    isinstance(item, dict) and item.get("type") == "tool_result"
                    for item in converted[-1]["content"]
                )
            ):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
            continue
        if role == "assistant" and message.get("tool_calls"):
            blocks: list[dict] = []
            content = message.get("content")
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                raw_arguments = function.get("arguments", "{}")
                try:
                    parsed = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                except json.JSONDecodeError:
                    parsed = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(call.get("id", "")),
                        "name": str(function.get("name", "")),
                        "input": parsed if isinstance(parsed, dict) else {},
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
            continue
        if role in {"user", "assistant"}:
            converted.append({"role": role, "content": message.get("content", "")})
    return converted


def _openai_usage(raw: object) -> LLMUsage:
    if not isinstance(raw, dict):
        return LLMUsage()
    return LLMUsage(
        prompt_tokens=raw.get("prompt_tokens") if isinstance(raw.get("prompt_tokens"), int) else None,
        completion_tokens=(
            raw.get("completion_tokens") if isinstance(raw.get("completion_tokens"), int) else None
        ),
        total_tokens=raw.get("total_tokens") if isinstance(raw.get("total_tokens"), int) else None,
    )


def _parse_tool_arguments(raw: str) -> dict:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError("도구 호출 arguments가 올바른 JSON이 아닙니다.") from exc
    if not isinstance(value, dict):
        raise LLMError("도구 호출 arguments는 JSON 객체여야 합니다.")
    return value


def _parse_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("structured response is not a JSON object")
    return value


def _mock_tool_turn(
    messages: Sequence[dict],
    tools: Sequence[dict],
    force_tools: Sequence[str],
    *,
    system: str = "",
) -> ToolTurn:
    known = {
        str((tool.get("function") or {}).get("name"))
        for tool in tools
        if tool.get("type") == "function"
    }
    if force_tools:
        topic = _last_user_text(messages)
        return ToolTurn(
            "",
            [
                ToolCallRequest(
                    id=f"mock-{index}-{name}",
                    name=name,
                    arguments=_mock_tool_arguments(name, topic),
                )
                for index, name in enumerate(force_tools)
                if name in known
            ],
            MOCK_MODEL_NAME,
        )
    return ToolTurn(_mock_prefetched_answer(system, messages), [], MOCK_MODEL_NAME)


def _mock_prefetched_answer(system: str, messages: Sequence[dict]) -> str:
    try:
        context = json.loads(system.rsplit("\n", 1)[-1])
        results = context.get("course_materials", {}).get("results", [])
    except (json.JSONDecodeError, AttributeError):
        results = []
    if not results:
        return _mock_grounded_answer(messages)
    first = results[0]
    question = _last_user_text(messages)
    preview = " ".join(str(first.get("excerpt", "")).split())[:200]
    return (
        f"[모의 응답] '{question}'은(는) {first.get('source', '강의자료')}에서 "
        f"확인할 수 있어요. {preview}"
    )


def _mock_tool_arguments(name: str, topic: str) -> dict:
    if name == "recall_weak_concepts":
        return {"topic": topic}
    if name == "search_course_materials":
        return {"query": topic}
    return {}


def _last_user_text(messages: Sequence[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            return str(message["content"])
    return ""


def _mock_grounded_answer(messages: Sequence[dict]) -> str:
    question = _last_user_text(messages)
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        try:
            payload = json.loads(str(message.get("content") or "{}"))
        except json.JSONDecodeError:
            continue
        results = payload.get("results") if isinstance(payload, dict) else None
        if results:
            first = results[0]
            preview = " ".join(str(first.get("excerpt", "")).split())[:200]
            return (
                f"[모의 답변] '{question}'은(는) "
                f"{first.get('source', '강의자료')}에서 확인할 수 있어요. {preview}"
            )
    return f"[모의 답변] '{question}'에 대한 강의자료 근거를 찾지 못했어요."


def _mock_answer(messages: Sequence[ChatMessage]) -> str:
    user_message = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    question = _extract_block(user_message, "[질문]")
    context = _extract_block(user_message, "[강의자료 컨텍스트]")
    preview = " ".join(context.split())[:200]
    if preview:
        return (
            f"[모의 답변] '{question}'에 대해 강의자료를 근거로 정리하면 다음과 같습니다.\n"
            f"{preview}"
        )
    return f"[모의 답변] '{question}'에 대한 일반적인 개념 설명입니다."


def _extract_block(text: str, header: str) -> str:
    if header not in text:
        return text.strip()
    body = text.split(header, 1)[1]
    for next_header in ("[질문]", "[강의자료 컨텍스트]", "[답변 지침]"):
        if next_header != header and next_header in body:
            body = body.split(next_header, 1)[0]
    return body.strip()
