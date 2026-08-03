"""Answer generation.

All provider calls live here so the model can be swapped from configuration, and
a deterministic mock keeps the chat flow testable without an API key.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

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
        return MOCK_MODEL_NAME if self.settings.use_mock_llm else self.settings.chat_model

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

        return self._openai_answer(messages)

    def _openai_answer(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        if not self.settings.openai_api_key:
            raise LLMError(
                "OPENAI_API_KEY가 설정되지 않았습니다. USE_MOCK_LLM=true로 두거나 키를 설정하세요."
            )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key)
            response = client.chat.completions.create(
                model=self.settings.chat_model,
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
                messages=[
                    {"role": message.role, "content": message.content} for message in messages
                ],
            )
        except LLMError:
            raise
        except Exception as error:
            raise LLMError(f"답변 생성에 실패했습니다: {error}") from error

        usage = getattr(response, "usage", None)
        return LLMResponse(
            answer=response.choices[0].message.content or "",
            model_name=self.settings.chat_model,
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            ),
        )


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
