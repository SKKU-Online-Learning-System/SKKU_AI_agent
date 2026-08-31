from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol, Sequence

from openai import AsyncOpenAI

from skku_ai_rag.config import RagConfig
from skku_ai_rag.vector_store import SearchHit

RAG_SYSTEM_PROMPT = """너는 성균관대학교 수업을 돕는 교육용 코스 에이전트다.

반드시 제공된 강의자료 컨텍스트를 우선 근거로 답변한다.
강의자료에 없는 내용은 확정적으로 말하지 않는다.
출처가 부족하면 “강의자료에서 직접 확인된 내용이 부족합니다”라고 말한다.
과제나 시험의 정답을 직접 요구하는 경우, 정답을 그대로 제공하지 말고 개념 설명, 접근 방법, 단계별 힌트를 제공한다.
학생이 스스로 이해할 수 있도록 친절하고 명확하게 답변한다.
답변은 기본적으로 한국어로 작성한다. 사용자가 영어로 질문하면 영어 답변도 허용한다."""


class LLMError(Exception):
    pass


class LLMConfigurationError(LLMError):
    pass


class LLMGenerationError(LLMError):
    pass


@dataclass(frozen=True)
class PromptMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class BuiltPrompt:
    system: str
    messages: list[PromptMessage]


@dataclass(frozen=True)
class PromptChunk:
    material_id: str
    document_name: str
    chunk_index: int
    chunk_text: str
    score: float
    page_number: Optional[int] = None


@dataclass(frozen=True)
class LLMOptions:
    model_name: str
    temperature: float
    max_tokens: int


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class LLMResponse:
    answer: str
    model_name: str
    usage: LLMUsage


class LLMService(Protocol):
    async def generate_answer(
        self,
        prompt: BuiltPrompt,
        options: LLMOptions,
    ) -> LLMResponse:
        raise NotImplementedError


class PromptBuilderService:
    def __init__(self, *, top_k: int = 5, max_context_chars: int = 12000) -> None:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")
        self.top_k = top_k
        self.max_context_chars = max_context_chars

    def build_rag_prompt(
        self,
        *,
        course_name: str,
        question: str,
        retrieved_chunks: Sequence[PromptChunk],
        answer_policy: Optional[str] = None,
        safety_context: Optional[str] = None,
    ) -> BuiltPrompt:
        system_parts = [RAG_SYSTEM_PROMPT]
        if answer_policy:
            system_parts.append(f"답변 정책:\n{answer_policy}")
        if safety_context:
            system_parts.append(f"안전 지침:\n{safety_context}")

        context = self._format_context(retrieved_chunks[: self.top_k])
        user_content = (
            f"과목: {course_name}\n"
            f"질문: {question}\n\n"
            f"강의자료 컨텍스트:\n{context or '검색된 강의자료 없음'}"
        )
        return BuiltPrompt(
            system="\n\n".join(system_parts),
            messages=[PromptMessage(role="user", content=user_content)],
        )

    def _format_context(self, chunks: Sequence[PromptChunk]) -> str:
        blocks: list[str] = []
        remaining = self.max_context_chars
        for chunk in chunks:
            page = f", page={chunk.page_number}" if chunk.page_number is not None else ""
            header = (
                f"[{chunk.document_name}{page}, chunk={chunk.chunk_index}, "
                f"score={chunk.score:.3f}]"
            )
            separator_cost = 6 if blocks else 0
            available = remaining - len(header) - 1 - separator_cost
            if available <= 0:
                break
            body = chunk.chunk_text[:available]
            blocks.append(f"{header}\n{body}")
            remaining -= len(header) + 1 + len(body) + separator_cost
            if len(body) < len(chunk.chunk_text):
                break
        return "\n\n---\n\n".join(blocks)


class MockLLMService:
    async def generate_answer(
        self,
        prompt: BuiltPrompt,
        options: LLMOptions,
    ) -> LLMResponse:
        content = prompt.messages[-1].content if prompt.messages else ""
        answer = f"[MOCK LLM]\n{content}"
        return LLMResponse(
            answer=answer,
            model_name=f"mock:{options.model_name}",
            usage=LLMUsage(
                prompt_tokens=self._estimate_tokens(prompt.system + content),
                completion_tokens=self._estimate_tokens(answer),
            ),
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)


class QwenLLMService:
    def __init__(self, api_key: Optional[str], base_url: str, enable_thinking: bool) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.enable_thinking = enable_thinking

    async def generate_answer(
        self,
        prompt: BuiltPrompt,
        options: LLMOptions,
    ) -> LLMResponse:
        if not self.api_key:
            raise LLMConfigurationError(
                "LLM_API_KEY_MISSING: QWEN_API_KEY is required when USE_MOCK_LLM=false"
            )
        try:
            response = await AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            ).chat.completions.create(
                model=options.model_name,
                max_completion_tokens=options.max_tokens,
                temperature=options.temperature,
                extra_body={"enable_thinking": self.enable_thinking},
                messages=[
                    {"role": "system", "content": prompt.system},
                    *[
                        {"role": message.role, "content": message.content}
                        for message in prompt.messages
                    ],
                ],
            )
            answer = (response.choices[0].message.content or "").strip()
            if not answer:
                raise LLMGenerationError("LLM_RESPONSE_EMPTY: Qwen returned no text")
            return LLMResponse(
                answer=answer,
                model_name=response.model,
                usage=LLMUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                ),
            )
        except LLMGenerationError:
            raise
        except Exception as exc:
            raise LLMGenerationError("LLM_GENERATION_FAILED: Qwen request failed") from exc


def create_llm_service(config: RagConfig) -> LLMService:
    if config.use_mock_llm:
        return MockLLMService()
    return QwenLLMService(
        config.qwen_api_key,
        config.qwen_base_url,
        config.qwen_enable_thinking,
    )


class AnswerGenerator:
    """Compatibility facade for the existing retrieval package and the Stage 4 chat API."""

    def __init__(
        self,
        config: RagConfig,
        *,
        llm_service: Optional[LLMService] = None,
        prompt_builder: Optional[PromptBuilderService] = None,
    ) -> None:
        self.config = config
        self.llm_service = llm_service or create_llm_service(config)
        self.prompt_builder = prompt_builder or PromptBuilderService(
            top_k=config.top_k,
            max_context_chars=config.max_context_chars,
        )

    async def generate_response(
        self,
        question: str,
        hits: list[SearchHit],
        *,
        course_name: str = "",
        answer_policy: Optional[str] = None,
        safety_context: Optional[str] = None,
    ) -> LLMResponse:
        prompt = self.prompt_builder.build_rag_prompt(
            course_name=course_name,
            question=question,
            retrieved_chunks=[self._to_prompt_chunk(hit) for hit in hits],
            answer_policy=answer_policy,
            safety_context=safety_context,
        )
        return await self.llm_service.generate_answer(
            prompt,
            LLMOptions(
                model_name=self.config.qwen_model,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
            ),
        )

    async def generate(self, question: str, hits: list[SearchHit]) -> str:
        return (await self.generate_response(question, hits)).answer

    @staticmethod
    def _to_prompt_chunk(hit: SearchHit) -> PromptChunk:
        metadata = hit.record.metadata
        page_number = metadata.get("page")
        chunk_index = metadata.get("chunk_index")
        return PromptChunk(
            material_id=hit.record.material_id,
            document_name=str(metadata.get("title", hit.record.material_id)),
            page_number=page_number if isinstance(page_number, int) else None,
            chunk_index=chunk_index if isinstance(chunk_index, int) else 0,
            chunk_text=hit.record.content,
            score=hit.score,
        )
