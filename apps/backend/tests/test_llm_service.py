from types import SimpleNamespace

import anthropic
import pytest

from app.core.config import Settings
from app.services.llm_service import ChatMessage, LLMError, LLMService


def test_claude_uses_top_level_system_and_text_blocks(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeMessages:
        def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                model="claude-test",
                content=[
                    SimpleNamespace(type="text", text="강의자료 "),
                    SimpleNamespace(type="tool_use"),
                    SimpleNamespace(type="text", text="기반 답변"),
                ],
                usage=SimpleNamespace(input_tokens=100, output_tokens=30),
            )

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: FakeClient())
    service = LLMService(
        Settings(
            anthropic_api_key="test-key",
            claude_model="claude-test",
            use_mock_llm=False,
        )
    )

    response = service.generate_answer(
        [ChatMessage("system", "규칙"), ChatMessage("user", "질문")]
    )

    assert response.answer == "강의자료 기반 답변"
    assert response.model_name == "claude-test"
    assert response.usage.total_tokens == 130
    assert calls[0]["system"] == "규칙"
    assert calls[0]["messages"] == [{"role": "user", "content": "질문"}]


def test_claude_requires_api_key() -> None:
    service = LLMService(Settings(use_mock_llm=False, anthropic_api_key=None))

    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        service.generate_answer([ChatMessage("user", "질문")])
