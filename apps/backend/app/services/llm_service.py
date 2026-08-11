"""Answer generation.

All provider calls live here so the model can be swapped from configuration, and
a deterministic mock keeps the chat flow testable without an API key.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional, Sequence, cast
from urllib.parse import urlparse

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
        return MOCK_MODEL_NAME if self.settings.use_mock_llm else self.settings.claude_model

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

        return self._claude_answer(messages)

    def _claude_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        if not self.settings.anthropic_api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                "USE_MOCK_LLM=true로 두거나 키를 설정하세요."
            )

        try:
            from anthropic import Anthropic
            from anthropic.types import MessageParam

            system = "\n\n".join(
                message.content for message in messages if message.role == "system"
            )
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
        except LLMError:
            raise
        except Exception as error:
            raise LLMError("Claude 답변 생성에 실패했습니다.") from error

        answer = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
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


    # ----------------------------------------------------------------- tools
    #
    # The voice teaching assistant needs a tool-using, streaming turn. It runs
    # on the same provider and the same mock as the text chatbot so the whole
    # product keeps one answer-generation boundary.

    def _require_client(self):
        if not self.settings.anthropic_api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
                "USE_MOCK_LLM=true로 두거나 키를 설정하세요."
            )
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
        max_tokens: Optional[int] = None,
    ) -> ToolTurn:
        """Run one Claude turn that may call tools, streaming any text it writes.

        Args:
            system: System prompt for the turn.
            messages: Anthropic-shaped conversation, newest last.
            tools: Anthropic-shaped tool schemas.
            force_tools: Tool names the caller needs before an answer; a
                non-empty value forbids Claude from replying without a tool.
            on_token: Optional async callback receiving streamed text deltas.
            max_tokens: Overrides the configured answer budget.

        Returns:
            The assistant text and any tool calls it requested.
        """
        if self.settings.use_mock_llm:
            turn = _mock_tool_turn(messages, tools, force_tools)
            if on_token and turn.text:
                await on_token(turn.text)
            return turn

        client = self._require_client()
        request = {
            "model": self.settings.claude_model,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "system": system,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": {"type": "any"} if force_tools else {"type": "auto"},
        }

        try:
            if on_token is None:
                message = await client.messages.create(**request)
            else:
                async with client.messages.stream(**request) as stream:
                    async for event in stream:
                        if event.type == "text" and event.text:
                            await on_token(event.text)
                    message = await stream.get_final_message()
        except LLMError:
            raise
        except Exception as error:
            raise LLMError("Claude 답변 생성에 실패했습니다.") from error

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                arguments = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(ToolCallRequest(block.id, block.name, arguments))

        return ToolTurn(
            text="".join(text_parts),
            tool_calls=tool_calls,
            model_name=message.model,
        )

    async def search_web(
        self,
        *,
        query: str,
        system: str,
        allowed_domains: Sequence[str],
        max_uses: int = 3,
    ) -> WebSearchAnswer:
        """Answer from Claude's server-side web search, limited to an allowlist.

        Args:
            query: Focused search query.
            system: System prompt describing how to answer.
            allowed_domains: Only these hosts may be searched or cited.
            max_uses: Upper bound on searches for this call.

        Returns:
            The cited answer and the trusted source URLs backing it.
        """
        if self.settings.use_mock_llm:
            raise LLMError("모의 LLM 모드에서는 신뢰 웹 검색을 사용할 수 없습니다.")
        if not allowed_domains:
            raise LLMError("신뢰 사이트가 비어 있어 웹 검색을 실행할 수 없습니다.")

        client = self._require_client()
        try:
            message = await client.messages.create(
                model=self.settings.claude_model,
                max_tokens=self.settings.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": query}],
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": max_uses,
                        "allowed_domains": list(allowed_domains),
                    }
                ],
            )
        except Exception as error:
            raise LLMError("신뢰 웹 검색에 실패했습니다.") from error

        text_parts: list[str] = []
        urls: list[str] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "web_search_tool_result":
                for result in getattr(block, "content", None) or []:
                    url = getattr(result, "url", None)
                    if url:
                        urls.append(url)

        return WebSearchAnswer(
            answer="".join(text_parts).strip(),
            # Re-check the allowlist locally: never trust the provider to have
            # honoured the filter before we show a link to a student.
            sources=[url for url in dict.fromkeys(urls) if _host_allowed(url, allowed_domains)],
            model_name=message.model,
        )


def _host_allowed(url: str, allowed_domains: Sequence[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def _mock_tool_turn(
    messages: Sequence[dict],
    tools: Sequence[dict],
    force_tools: Sequence[str],
) -> ToolTurn:
    """Deterministic tool-using turn so the voice assistant runs without a key."""

    known = {tool["name"] for tool in tools}
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
        text=_mock_grounded_answer(messages),
        tool_calls=[],
        model_name=MOCK_MODEL_NAME,
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
