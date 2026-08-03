from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from typing import Protocol

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

    def _validate_and_log(self, texts: Sequence[str]) -> None:
        for text in texts:
            if not text.strip():
                raise EmbeddingError("EMBEDDING_EMPTY_TEXT: Text must not be empty")
            if len(text) > self.max_input_chars:
                raise EmbeddingError(
                    "EMBEDDING_INPUT_TOO_LONG: Text exceeds embedding input limit"
                )
        logger.info(
            "Embedding batch model=%s chunk_count=%d total_chars=%d",
            self.model_name,
            len(texts),
            sum(len(text) for text in texts),
        )


class LocalHashEmbeddingService(BaseEmbeddingService):
    def __init__(self, dimensions: int = 128, max_input_chars: int = 12000) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        super().__init__(f"local-hash-{dimensions}", max_input_chars)
        self.dimensions = dimensions

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._validate_and_log(texts)
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


def create_embedding_service(_settings: Settings) -> EmbeddingService:
    return LocalHashEmbeddingService()
