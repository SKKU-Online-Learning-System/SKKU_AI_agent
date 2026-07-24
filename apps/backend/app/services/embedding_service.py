from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from typing import Optional, Protocol

from openai import OpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class EmbeddingService(Protocol):
    @property
    def model_name(self) -> str:
        raise NotImplementedError

    def embed_text(self, text: str) -> list[float]:
        raise NotImplementedError

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class BaseEmbeddingService:
    def __init__(self, model_name: str, max_input_chars: int = 12000) -> None:
        self.model_name = model_name
        self.max_input_chars = max_input_chars

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    def _validate_and_log(self, texts: Sequence[str], *, mock: bool) -> None:
        for text in texts:
            if not text.strip():
                raise EmbeddingError("EMBEDDING_EMPTY_TEXT: Text must not be empty")
            if len(text) > self.max_input_chars:
                raise EmbeddingError(
                    "EMBEDDING_INPUT_TOO_LONG: Text exceeds embedding input limit"
                )
        logger.info(
            "Embedding batch model=%s mock=%s chunk_count=%d total_chars=%d",
            self.model_name,
            mock,
            len(texts),
            sum(len(text) for text in texts),
        )


class DeterministicMockEmbeddingService(BaseEmbeddingService):
    def __init__(self, dimensions: int = 128, max_input_chars: int = 12000) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        super().__init__(f"mock-hash-{dimensions}", max_input_chars)
        self.dimensions = dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._validate_and_log(texts, mock=True)
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"\w+", text.casefold()) or [text]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        magnitude = sum(value * value for value in vector) ** 0.5
        if magnitude == 0:
            return vector
        return [value / magnitude for value in vector]


class OpenAIEmbeddingService(BaseEmbeddingService):
    def __init__(
        self,
        api_key: Optional[str],
        model_name: str = "text-embedding-3-small",
        max_input_chars: int = 12000,
    ) -> None:
        super().__init__(model_name, max_input_chars)
        self.api_key = api_key
        self._client: Optional[OpenAI] = None

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._validate_and_log(texts, mock=False)
        if not self.api_key:
            raise EmbeddingError(
                "EMBEDDING_API_KEY_MISSING: OPENAI_API_KEY is required "
                "when USE_MOCK_EMBEDDING=false"
            )
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key)
        try:
            response = self._client.embeddings.create(
                model=self.model_name,
                input=list(texts),
            )
        except Exception as exc:
            raise EmbeddingError(
                "EMBEDDING_API_ERROR: OpenAI embedding request failed"
            ) from exc
        embeddings = [
            list(item.embedding)
            for item in sorted(response.data, key=lambda item: item.index)
        ]
        if len(embeddings) != len(texts):
            raise EmbeddingError(
                "EMBEDDING_RESPONSE_INVALID: Embedding count does not match input count"
            )
        return embeddings


def create_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.use_mock_embedding:
        return DeterministicMockEmbeddingService()
    return OpenAIEmbeddingService(
        api_key=settings.openai_api_key,
        model_name=settings.embedding_model,
    )
