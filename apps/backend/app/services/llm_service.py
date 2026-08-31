"""Answer generation.

All provider calls live here so the model can be swapped from configuration, and
a deterministic mock keeps the chat flow testable without an API key.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Sequence
from urllib.parse import urlparse

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

MOCK_MODEL_NAME = "mock-llm"


class LLMError(Exception):
    code = "LLM_GENERATION_FAILED"


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ToolCallRequest:
    """One tool the model asked to run, with arguments already parsed."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ToolTurn:
    """One assistant turn: free text, tool requests, or both."""

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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def model_name(self) -> str:
        return MOCK_MODEL_NAME if self.settings.use_mock_llm else self.settings.qwen_model

    def generate_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        if not messages:
            raise LLMError("생성할 메시지가 없습니다.")

        logger.info(
            "Generating an answer with %s from %d message(s), %d prompt chars",
            self.model_name,
            len(messages),
            sum(len(message.content) for message in messages),
        )

        if self.settings.use_mock_llm:
            return LLMResponse(
                answer=_mock_answer(messages),
                model_name=MOCK_MODEL_NAME,
                usage=LLMUsage(),
            )

        return self._qwen_answer(messages)

    def _qwen_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        try:
            response = self._sync_client().chat.completions.create(
                model=self.settings.qwen_model,
                max_completion_tokens=self.settings.llm_max_tokens,
                temperature=self.settings.llm_temperature,
                extra_body={"enable_thinking": self.settings.qwen_enable_thinking},
                messages=[
                    {"role": message.role, "content": message.content} for message in messages
                ],
            )
        except LLMError:
            raise
        except Exception as error:
            raise LLMError("Qwen 답변 생성에 실패했습니다.") from error

        answer = _text_content(response.choices[0].message.content).strip()
        if not answer:
            raise LLMError("Qwen이 빈 답변을 반환했습니다.")

        prompt_tokens = getattr(response.usage, "prompt_tokens", None)
        completion_tokens = getattr(response.usage, "completion_tokens", None)
        return LLMResponse(
            answer=answer,
            model_name=response.model,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=getattr(response.usage, "total_tokens", None),
            ),
        )

    # ----------------------------------------------------------------- tools
    #
    # The voice teaching assistant needs a tool-using, streaming turn. It runs
    # on the same provider and the same mock as the text chatbot so the whole
    # product keeps one answer-generation boundary.

    def _require_api_key(self) -> str:
        key = (self.settings.qwen_api_key or "").strip()
        if not key:
            raise LLMError(
                "QWEN_API_KEY가 설정되지 않았습니다. "
                "USE_MOCK_LLM=true로 두거나 키를 설정하세요."
            )
        return key

    def _sync_client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self._require_api_key(),
            base_url=self.settings.qwen_base_url,
        )

    def _async_client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=self._require_api_key(),
            base_url=self.settings.qwen_base_url,
        )

    async def stream_tool_turn(
        self,
        *,
        system: str,
        messages: Sequence[dict],
        tools: Sequence[dict],
        force_tools: Sequence[str] = (),
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        max_tokens: Optional[int] = None,
    ) -> ToolTurn:
        """Run one Qwen turn that may call tools, streaming any text it writes.

        Args:
            system: System prompt for the turn.
            messages: OpenAI-shaped conversation, newest last.
            tools: OpenAI-shaped function tool schemas.
            force_tools: Tool names the caller needs before an answer; a
                single value forces Qwen to call that tool.
            on_token: Optional async callback receiving streamed text deltas.
            max_tokens: Overrides the configured answer budget.

        Returns:
            The assistant text and any tool calls it requested.
        """
        if self.settings.use_mock_llm:
            turn = _mock_tool_turn(messages, tools, force_tools, system=system)
            if on_token and turn.text:
                await on_token(turn.text)
            return turn

        client = self._async_client()
        provider_messages = [{"role": "system", "content": system}, *messages]
        request = {
            "model": self.settings.qwen_model,
            "max_completion_tokens": max_tokens or self.settings.llm_max_tokens,
            "temperature": self.settings.llm_temperature,
            "extra_body": {"enable_thinking": self.settings.qwen_enable_thinking},
            "messages": provider_messages,
            "tools": list(tools),
            "tool_choice": _qwen_tool_choice(force_tools),
            "parallel_tool_calls": True,
        }

        try:
            if on_token is None:
                response = await client.chat.completions.create(**request)
                message = response.choices[0].message
                return ToolTurn(
                    text=_text_content(message.content),
                    tool_calls=_tool_call_requests(message.tool_calls),
                    model_name=response.model,
                )
            else:
                stream = await client.chat.completions.create(**request, stream=True)
                text_parts: list[str] = []
                tool_parts: dict[int, dict[str, str]] = {}
                model_name = self.settings.qwen_model
                async for chunk in stream:
                    model_name = chunk.model or model_name
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        text_parts.append(delta.content)
                        await on_token(delta.content)
                    for call in delta.tool_calls or []:
                        part = tool_parts.setdefault(
                            call.index,
                            {"id": "", "name": "", "arguments": ""},
                        )
                        if call.id:
                            part["id"] = call.id
                        function = call.function
                        if function and function.name:
                            part["name"] += function.name
                        if function and function.arguments:
                            part["arguments"] += function.arguments
                return ToolTurn(
                    text="".join(text_parts),
                    tool_calls=[
                        ToolCallRequest(
                            id=part["id"],
                            name=part["name"],
                            arguments=_parse_tool_arguments(part["arguments"]),
                        )
                        for _, part in sorted(tool_parts.items())
                    ],
                    model_name=model_name,
                )
        except LLMError:
            raise
        except Exception as error:
            raise LLMError("Qwen 답변 생성에 실패했습니다.") from error

    async def generate_json(self, *, system: str, payload: dict, max_tokens: int = 900) -> dict:
        """Generate one JSON object through the configured provider boundary."""
        if self.settings.use_mock_llm:
            return {"save": None, "reviews": []}
        client = self._async_client()
        try:
            response = await client.chat.completions.create(
                model=self.settings.qwen_model,
                max_completion_tokens=max_tokens,
                temperature=self.settings.llm_temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
                extra_body={"enable_thinking": False},
            )
            raw = _text_content(response.choices[0].message.content).strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json.loads(raw)
        except Exception as error:
            raise LLMError("구조화 JSON 생성에 실패했습니다.") from error
        if not isinstance(result, dict):
            raise LLMError("구조화 응답이 JSON 객체가 아닙니다.")
        return result

    async def search_web(
        self,
        *,
        query: str,
        system: str,
        allowed_domains: Sequence[str],
        max_uses: int = 3,
    ) -> WebSearchAnswer:
        """Answer with Qwen's native web search and verify every returned host.

        Args:
            query: Focused search query.
            system: System prompt describing how to answer.
            allowed_domains: Only these hosts may be searched or cited.
            max_uses: Maximum number of verified source URLs to return.

        Returns:
            The cited answer and the trusted source URLs backing it.
        """
        if self.settings.use_mock_llm:
            raise LLMError("모의 LLM 모드에서는 신뢰 웹 검색을 사용할 수 없습니다.")
        if not allowed_domains:
            raise LLMError("신뢰 사이트가 비어 있어 웹 검색을 실행할 수 없습니다.")

        key = self._require_api_key()
        allowed_query = " OR ".join(f"site:{domain}" for domain in allowed_domains)
        endpoint = (
            f"{self.settings.qwen_dashscope_base_url.rstrip('/')}"
            "/services/aigc/multimodal-generation/generation"
        )
        answer_parts: list[str] = []
        results: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "X-DashScope-SSE": "enable",
                    },
                    json={
                        "model": self.settings.qwen_web_search_model,
                        "input": {
                            "messages": [
                                {
                                    "role": "system",
                                    "content": [
                                        {
                                            "text": (
                                                f"{system}\nSearch and answer only from these "
                                                f"domains: {', '.join(allowed_domains)}."
                                            )
                                        }
                                    ],
                                },
                                {
                                    "role": "user",
                                    "content": [{"text": f"({allowed_query}) {query}"}],
                                },
                            ]
                        },
                        "parameters": {
                            "result_format": "message",
                            "enable_thinking": self.settings.qwen_enable_thinking,
                            "enable_search": True,
                            "incremental_output": True,
                            "search_options": {
                                "enable_source": True,
                            },
                        },
                    },
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line.removeprefix("data:").strip()
                        if not raw or raw == "[DONE]":
                            continue
                        event = json.loads(raw)
                        if event.get("code"):
                            raise LLMError("Qwen 웹 검색 API가 오류를 반환했습니다.")
                        output = event.get("output") or {}
                        choices = output.get("choices") or []
                        if choices:
                            answer_parts.append(
                                _dashscope_text(choices[0].get("message", {}).get("content"))
                            )
                        search_info = output.get("search_info") or {}
                        if search_info.get("search_results"):
                            results = search_info["search_results"]
        except LLMError:
            raise
        except Exception as error:
            raise LLMError("신뢰 웹 검색에 실패했습니다.") from error

        answer = "".join(answer_parts)
        urls = [result.get("url") for result in results if result.get("url")]
        disallowed = [url for url in urls if not _host_allowed(url, allowed_domains)]
        if not answer.strip() or not urls:
            raise LLMError("신뢰 웹 검색이 인용 가능한 답변을 반환하지 않았습니다.")
        if disallowed:
            logger.warning("Rejected Qwen web search with disallowed sources: %s", disallowed)
            raise LLMError("신뢰 목록 밖의 출처가 포함되어 웹 검색 결과를 거부했습니다.")

        return WebSearchAnswer(
            answer=answer.strip(),
            sources=list(dict.fromkeys(urls))[:max_uses],
            model_name=self.settings.qwen_web_search_model,
        )


def _text_content(content: object) -> str:
    """Normalize the text-only content returned by OpenAI-compatible clients."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )


def _dashscope_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(part.get("text", "")) for part in content if isinstance(part, dict)
    )


def _parse_tool_arguments(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError as error:
        raise LLMError("Qwen 도구 호출 인자를 해석하지 못했습니다.") from error
    if not isinstance(parsed, dict):
        raise LLMError("Qwen 도구 호출 인자가 JSON 객체가 아닙니다.")
    return parsed


def _tool_call_requests(tool_calls: object) -> list[ToolCallRequest]:
    requests: list[ToolCallRequest] = []
    for call in tool_calls or []:
        function = getattr(call, "function", None)
        if function is None:
            continue
        requests.append(
            ToolCallRequest(
                id=getattr(call, "id", ""),
                name=getattr(function, "name", ""),
                arguments=_parse_tool_arguments(getattr(function, "arguments", "")),
            )
        )
    return requests


def _qwen_tool_choice(force_tools: Sequence[str]) -> object:
    if not force_tools:
        return "auto"
    if len(force_tools) > 1:
        raise LLMError("Qwen은 한 요청에서 하나의 도구만 강제할 수 있습니다.")
    return {"type": "function", "function": {"name": force_tools[0]}}


def _host_allowed(url: str, allowed_domains: Sequence[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def _mock_tool_turn(
    messages: Sequence[dict],
    tools: Sequence[dict],
    force_tools: Sequence[str],
    *,
    system: str = "",
) -> ToolTurn:
    """Deterministic tool-using turn so the voice assistant runs without a key."""

    known = {
        tool["function"]["name"]
        for tool in tools
        if isinstance(tool.get("function"), dict) and tool["function"].get("name")
    }
    if force_tools:
        topic = _last_user_text(messages)
        return ToolTurn(
            text="",
            tool_calls=[
                ToolCallRequest(
                    id=f"mock-{index}-{name}",
                    name=name,
                    arguments=_mock_tool_arguments(name, topic),
                )
                for index, name in enumerate(force_tools)
                if name in known
            ],
            model_name=MOCK_MODEL_NAME,
        )

    return ToolTurn(
        text=_mock_prefetched_answer(system, messages),
        tool_calls=[],
        model_name=MOCK_MODEL_NAME,
    )


def _mock_prefetched_answer(system: str, messages: Sequence[dict]) -> str:
    """Ground the mock response in the server-prefetched course context."""
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
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _mock_grounded_answer(messages: Sequence[dict]) -> str:
    """Summarise the newest course-material tool result, or say it is missing."""

    question = _last_user_text(messages)
    for message in reversed(messages):
        if message.get("role") == "tool" and isinstance(message.get("content"), str):
            try:
                payload = json.loads(message["content"])
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
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            try:
                payload = json.loads(block.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            results = payload.get("results") if isinstance(payload, dict) else None
            if not results:
                continue
            first = results[0]
            preview = " ".join(str(first.get("excerpt", "")).split())[:200]
            return (
                f"[모의 답변] '{question}'은(는) {first.get('source', '강의자료')}에서 확인할 수 있어요. "
                f"{preview}"
            )

    return f"[모의 답변] '{question}'에 대한 강의자료 근거를 찾지 못했어요."


def _mock_answer(messages: Sequence[ChatMessage]) -> str:
    """Echo the question and a short context preview so the RAG flow stays verifiable."""

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
        if next_header in body:
            body = body.split(next_header, 1)[0]

    return body.strip()
