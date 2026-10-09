import logging

import pytest

from app.core.config import Settings
from app.services.embedding_service import (
    EmbeddingError,
    EmbeddingService,
    LocalHashEmbeddingService,
    create_embedding_service,
)


def test_local_embedding_is_deterministic_normalized_and_batch_capable() -> None:
    service = LocalHashEmbeddingService()

    first = service.embed_text("경사 하강법 gradient descent")
    repeated, different = service.embed_texts(
        ["경사 하강법 gradient descent", "과적합 regularization"]
    )

    assert len(first) == 128
    assert first == repeated
    assert first != different
    assert sum(value * value for value in first) == pytest.approx(1.0)
    assert service.model_name == "local-hash-128"


def test_factory_defaults_to_real_qwen_embeddings() -> None:
    service = create_embedding_service(Settings(_env_file=None))

    assert isinstance(service, EmbeddingService)
    assert service.model_name == "Qwen/Qwen3-VL-Embedding-2B:2048"


def test_embedding_rejects_oversized_input() -> None:
    service = LocalHashEmbeddingService(max_input_chars=4)

    with pytest.raises(EmbeddingError, match="EMBEDDING_INPUT_TOO_LONG"):
        service.embed_text("12345")


def test_embedding_log_contains_only_batch_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    secret_text = "private lecture content"

    LocalHashEmbeddingService().embed_texts([secret_text, "second"])

    assert "chunk_count=2" in caplog.text
    assert "total_chars=29" in caplog.text
    assert secret_text not in caplog.text
