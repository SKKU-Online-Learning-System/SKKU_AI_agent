import logging
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services import embedding_service as embedding_module
from app.services.embedding_service import (
    DeterministicMockEmbeddingService,
    EmbeddingError,
    OpenAIEmbeddingService,
    create_embedding_service,
)


def test_mock_embedding_is_deterministic_normalized_and_batch_capable() -> None:
    service = DeterministicMockEmbeddingService()

    first = service.embed_text("경사 하강법 gradient descent")
    repeated, different = service.embed_texts(
        ["경사 하강법 gradient descent", "과적합 regularization"]
    )

    assert len(first) == 128
    assert first == repeated
    assert first != different
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert service.model_name == "mock-hash-128"


def test_openai_embedding_uses_configured_model_and_preserves_response_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeEmbeddings:
        def create(self, **kwargs: object) -> SimpleNamespace:
            calls.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                    SimpleNamespace(index=0, embedding=[1.0, 0.0]),
                ]
            )

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(
        embedding_module,
        "OpenAI",
        lambda **kwargs: FakeClient(),
    )
    service = OpenAIEmbeddingService("test-key", model_name="custom-embedding")

    result = service.embed_texts(["first", "second"])

    assert result == [[1.0, 0.0], [0.0, 1.0]]
    assert calls == [
        {
            "model": "custom-embedding",
            "input": ["first", "second"],
        }
    ]


def test_openai_embedding_requires_key_when_mock_is_disabled() -> None:
    service = create_embedding_service(
        Settings(use_mock_embedding=False, openai_api_key=None)
    )

    with pytest.raises(EmbeddingError, match="EMBEDDING_API_KEY_MISSING"):
        service.embed_text("lecture")


def test_openai_api_failure_has_stable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingEmbeddings:
        def create(self, **kwargs: object) -> None:
            raise RuntimeError("secret provider error")

    class FailingClient:
        embeddings = FailingEmbeddings()

    monkeypatch.setattr(
        embedding_module,
        "OpenAI",
        lambda **kwargs: FailingClient(),
    )

    with pytest.raises(
        EmbeddingError,
        match="EMBEDDING_API_ERROR: OpenAI embedding request failed",
    ):
        OpenAIEmbeddingService("test-key").embed_text("lecture")


def test_embedding_rejects_oversized_input() -> None:
    service = DeterministicMockEmbeddingService(max_input_chars=4)

    with pytest.raises(EmbeddingError, match="EMBEDDING_INPUT_TOO_LONG"):
        service.embed_text("12345")


def test_embedding_log_contains_only_batch_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    secret_text = "private lecture content"

    DeterministicMockEmbeddingService().embed_texts([secret_text, "second"])

    assert "chunk_count=2" in caplog.text
    assert "total_chars=29" in caplog.text
    assert secret_text not in caplog.text
