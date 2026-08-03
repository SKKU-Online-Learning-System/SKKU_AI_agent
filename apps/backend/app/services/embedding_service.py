<<<<<<< HEAD
"""Chunk and question embeddings.

One place owns the OpenAI call so the provider stays swappable, and a
deterministic local provider keeps the whole pipeline testable without a key.
"""

=======
>>>>>>> refs/remotes/origin/main
from __future__ import annotations

import hashlib
import logging
import re
<<<<<<< HEAD
from typing import Sequence
=======
from collections.abc import Sequence
from typing import Protocol
>>>>>>> refs/remotes/origin/main

from app.core.config import Settings

logger = logging.getLogger(__name__)

<<<<<<< HEAD
MOCK_MODEL_PREFIX = "mock-hash"
MOCK_NGRAM_SIZES = (2, 3)
WHITESPACE = re.compile(r"\s+")


class EmbeddingError(Exception):
    code = "EMBEDDING_FAILED"


class EmbeddingService:
    """Turns text into vectors using OpenAI or a deterministic local fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def model_name(self) -> str:
        if self.settings.use_mock_embedding:
            return f"{MOCK_MODEL_PREFIX}-{self.settings.mock_embedding_dim}"
        return self.settings.embedding_model
=======

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
>>>>>>> refs/remotes/origin/main

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
<<<<<<< HEAD
        if not texts:
            return []

        prepared = [self._truncate(text) for text in texts]
        total_chars = sum(len(text) for text in prepared)
        logger.info(
            "Embedding %d text(s) with %s (%d chars total)",
            len(prepared),
            self.model_name,
            total_chars,
        )

        if self.settings.use_mock_embedding:
            return [self._mock_embedding(text) for text in prepared]

        return self._openai_embeddings(prepared)

    def _truncate(self, text: str) -> str:
        limit = self.settings.embedding_max_chars
        return text if len(text) <= limit else text[:limit]

    def _mock_embedding(self, text: str) -> list[float]:
        """Hash features into a fixed-size vector: the same text always maps to the same vector."""

        dimension = self.settings.mock_embedding_dim
        vector = [0.0] * dimension

        for feature in _mock_features(text):
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        return normalize(vector)

    def _openai_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.settings.openai_api_key:
            raise EmbeddingError(
                "OPENAI_API_KEY가 설정되지 않았습니다. USE_MOCK_EMBEDDING=true로 두거나 키를 설정하세요."
            )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key)
            response = client.embeddings.create(
                model=self.settings.embedding_model,
                input=list(texts),
            )
        except EmbeddingError:
            raise
        except Exception as error:
            raise EmbeddingError(f"임베딩 생성에 실패했습니다: {error}") from error

        return [item.embedding for item in response.data]


def _mock_features(text: str) -> list[str]:
    """Word tokens plus character n-grams.

    Korean attaches particles to stems, so whitespace tokens alone would make
    "경사하강법이" and "경사하강법은" look unrelated. Character n-grams keep the
    overlap that similarity search needs.
    """

    normalized = WHITESPACE.sub(" ", text.lower()).strip()
    if not normalized:
        return []

    features = normalized.split()
    condensed = normalized.replace(" ", "")
    for size in MOCK_NGRAM_SIZES:
        features.extend(
            condensed[index : index + size] for index in range(len(condensed) - size + 1)
        )

    return features


def normalize(vector: list[float]) -> list[float]:
    magnitude = sum(value * value for value in vector) ** 0.5
    if magnitude == 0:
        return vector

    return [value / magnitude for value in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0

    return dot / (left_norm * right_norm)
=======
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
>>>>>>> refs/remotes/origin/main
