"""Deterministic local embeddings for document chunks and questions."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Sequence

from app.core.config import Settings

logger = logging.getLogger(__name__)

MOCK_MODEL_PREFIX = "mock-hash"
MOCK_NGRAM_SIZES = (2, 3)
WHITESPACE = re.compile(r"\s+")


class EmbeddingError(Exception):
    code = "EMBEDDING_FAILED"


class EmbeddingService:
    """Turns text into vectors without an external embedding API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def model_name(self) -> str:
        return f"{MOCK_MODEL_PREFIX}-{self.settings.mock_embedding_dim}"

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
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

        return [self._mock_embedding(text) for text in prepared]

    def _truncate(self, text: str) -> str:
        limit = self.settings.embedding_max_chars
        return text if len(text) <= limit else text[:limit]

    def _mock_embedding(self, text: str) -> list[float]:
        return _hash_embedding(text, self.settings.mock_embedding_dim)


class LocalHashEmbeddingService:
    """Backward-compatible explicit local embedding service.

    The current RAG path uses :class:`EmbeddingService`; this class preserves
    the earlier public object API used by regression tests and integration code.
    """

    def __init__(self, dimension: int = 128, max_input_chars: int = 20_000) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        if max_input_chars <= 0:
            raise ValueError("max_input_chars must be positive")
        self.dimension = dimension
        self.max_input_chars = max_input_chars

    @property
    def model_name(self) -> str:
        return f"local-hash-{self.dimension}"

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        for text in texts:
            if len(text) > self.max_input_chars:
                raise EmbeddingError("EMBEDDING_INPUT_TOO_LONG")
        total_chars = sum(len(text) for text in texts)
        logger.info(
            "local embedding batch chunk_count=%d total_chars=%d model=%s",
            len(texts),
            total_chars,
            self.model_name,
        )
        return [_hash_embedding(text, self.dimension) for text in texts]


def create_embedding_service(settings: Settings) -> LocalHashEmbeddingService:
    """Return the deterministic local provider; no external embedding key is needed."""
    return LocalHashEmbeddingService(
        dimension=settings.mock_embedding_dim,
        max_input_chars=settings.embedding_max_chars,
    )


def _hash_embedding(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    for feature in _mock_features(text):
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return normalize(vector)


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
