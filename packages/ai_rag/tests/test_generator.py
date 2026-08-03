import asyncio
from types import SimpleNamespace

import pytest

from skku_ai_rag import generator as generator_module
from skku_ai_rag.config import RagConfig
from skku_ai_rag.generator import (
    AnswerGenerator,
    LLMConfigurationError,
    LLMGenerationError,
    MockLLMService,
    PromptBuilderService,
    PromptChunk,
    create_llm_service,
)
from skku_ai_rag.vector_store import SearchHit, VectorRecord


def sample_hit() -> SearchHit:
    return SearchHit(
        record=VectorRecord(
            id="chunk-1",
            course_id="course-1",
            material_id="material-1",
            content="경사하강법은 손실 함수를 줄이는 최적화 방법입니다.",
            embedding=[1.0],
            metadata={"title": "lecture1.pdf", "page": 12, "chunk_index": 3},
        ),
        score=0.87,
    )


def test_prompt_builder_applies_policy_sources_and_limits() -> None:
    builder = PromptBuilderService(top_k=1, max_context_chars=100)
    prompt = builder.build_rag_prompt(
        course_name="인공지능개론",
        question="경사하강법이 뭐야?",
        retrieved_chunks=[
            PromptChunk("m1", "lecture1.pdf", 3, "가" * 200, 0.87, 12),
            PromptChunk("m2", "secret.pdf", 0, "포함되면 안 됨", 0.8),
        ],
        answer_policy="힌트 중심",
        safety_context="정답 직접 제공 금지",
    )

    assert "성균관대학교" in prompt.system
    assert "힌트 중심" in prompt.system
    assert "정답 직접 제공 금지" in prompt.system
    assert prompt.messages[0].role == "user"
    assert "lecture1.pdf, page=12, chunk=3, score=0.870" in prompt.messages[0].content
    assert "secret.pdf" not in prompt.messages[0].content
    assert "가" * 101 not in prompt.messages[0].content


def test_mock_generator_is_deterministic_and_includes_retrieved_source() -> None:
    generator = AnswerGenerator(RagConfig(use_mock_llm=True))

    first = asyncio.run(
        generator.generate_response(
            "경사하강법이 뭐야?",
            [sample_hit()],
            course_name="인공지능개론",
        )
    )
    second = asyncio.run(
        generator.generate_response(
            "경사하강법이 뭐야?",
            [sample_hit()],
            course_name="인공지능개론",
        )
    )

    assert first == second
    assert first.model_name == "mock:claude-sonnet-5"
    assert "경사하강법은 손실 함수를 줄이는 최적화 방법입니다." in first.answer
    assert "lecture1.pdf, page=12, chunk=3" in first.answer
    assert first.usage.total_tokens > 0


def test_anthropic_service_uses_top_level_system_and_text_blocks(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeMessages:
        async def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                model="claude-test",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=300),
                content=[
                    SimpleNamespace(type="text", text="강의자료 "),
                    SimpleNamespace(type="tool_use"),
                    SimpleNamespace(type="text", text="기반 답변"),
                ],
            )

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(generator_module, "AsyncAnthropic", lambda **kwargs: FakeClient())
    generator = AnswerGenerator(
        RagConfig(
            anthropic_api_key="test-key",
            use_mock_llm=False,
            claude_model="claude-test",
            llm_temperature=0.4,
            llm_max_tokens=777,
        )
    )

    response = asyncio.run(generator.generate_response("질문", []))

    assert response.answer == "강의자료 기반 답변"
    assert response.model_name == "claude-test"
    assert response.usage.total_tokens == 1300
    assert calls[0]["model"] == "claude-test"
    assert calls[0]["max_tokens"] == 777
    assert calls[0]["temperature"] == 0.4
    assert "성균관대학교" in calls[0]["system"]
    assert all(message["role"] != "system" for message in calls[0]["messages"])


def test_real_service_requires_api_key() -> None:
    service = create_llm_service(RagConfig(use_mock_llm=False))
    prompt = PromptBuilderService().build_rag_prompt(
        course_name="과목",
        question="질문",
        retrieved_chunks=[],
    )

    with pytest.raises(LLMConfigurationError, match="ANTHROPIC_API_KEY"):
        asyncio.run(
            service.generate_answer(
                prompt,
                generator_module.LLMOptions("claude-sonnet-5", 0.2, 1024),
            )
        )


def test_anthropic_failure_uses_stable_error_without_prompt(monkeypatch) -> None:
    class FailingMessages:
        async def create(self, **kwargs: object) -> None:
            raise RuntimeError("provider leaked details")

    class FakeClient:
        messages = FailingMessages()

    monkeypatch.setattr(generator_module, "AsyncAnthropic", lambda **kwargs: FakeClient())
    generator = AnswerGenerator(RagConfig(anthropic_api_key="key", use_mock_llm=False))

    with pytest.raises(LLMGenerationError) as exc_info:
        asyncio.run(generator.generate("private question", []))

    assert str(exc_info.value) == "LLM_GENERATION_FAILED: Claude request failed"
    assert "private question" not in str(exc_info.value)


def test_rag_config_reads_llm_environment(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-env")
    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
    monkeypatch.setenv("LLM_MAX_TOKENS", "2048")

    config = RagConfig.from_env()

    assert config.anthropic_api_key == "env-key"
    assert config.claude_model == "claude-env"
    assert config.use_mock_llm is False
    assert config.llm_temperature == 0.5
    assert config.llm_max_tokens == 2048


def test_factory_returns_mock_without_api_key() -> None:
    assert isinstance(create_llm_service(RagConfig(use_mock_llm=True)), MockLLMService)
