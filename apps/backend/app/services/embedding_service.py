"""Qwen multimodal embeddings; deterministic hashing is explicit test mode only."""

from __future__ import annotations

import hashlib
import logging
import math

import httpx
import re
from typing import Sequence

from app.core.config import Settings
from app.services.model_server.client import sync_client

logger = logging.getLogger(__name__)

MOCK_MODEL_PREFIX = "mock-hash"
MOCK_NGRAM_SIZES = (2, 3)
WHITESPACE = re.compile(r"\s+")


class EmbeddingError(Exception):
    code = "EMBEDDING_FAILED"


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def model_name(self) -> str:
        if self.settings.embedding_provider == "mock":
            return f"{MOCK_MODEL_PREFIX}-{self.settings.mock_embedding_dim}"
        return f"{self.settings.embedding_model}:{self.settings.embedding_dimension}"

    def embed_text(self, text: str) -> list[float]:
        return self._embed(text, query=True)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_image(self, image_url: str) -> list[float]:
        return self._embed("", image_url=image_url)

    def _embed(
        self, text: str, *, query: bool = False, image_url: str | None = None,
    ) -> list[float]:
        if len(text) > self.settings.embedding_max_chars:
            raise EmbeddingError("EMBEDDING_INPUT_TOO_LONG")
        if self.settings.embedding_provider == "mock":
            if image_url:
                raise EmbeddingError("Mock embeddings do not support images")
            return _hash_embedding(text, self.settings.mock_embedding_dim)
        content = []
        if image_url:
            if not image_url.startswith("data:image/"):
                raise EmbeddingError("Only inline document images are supported")
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        if text.strip():
            content.append({"type": "text", "text": text})
        if not content:
            raise EmbeddingError("EMBEDDING_INPUT_EMPTY")
        instruction = (
            "Retrieve lecture pages relevant to the student's question or conversation."
            if query else "Represent the user's input."
        )
        try:
            response = sync_client(
                self.settings.embedding_base_url, self.settings.model_server_api_key,
                self.settings.embedding_timeout_seconds,
            ).post("embeddings", json={
                "model": self.settings.embedding_model,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": content},
                ],
                "add_generation_prompt": True,
                # Qwen VL pools the terminal <|endoftext|> added by its tokenizer.
                # vLLM chat defaults omit it, producing a different embedding space.
                "add_special_tokens": True,
                "encoding_format": "float",
            })
            response.raise_for_status()
            data = response.json()["data"]
            if len(data) != 1 or data[0]["index"] != 0:
                raise ValueError("Invalid embedding response count/index")
            vector = data[0]["embedding"]
            if not isinstance(vector, list) or len(vector) != 2048:
                raise ValueError("Unexpected Qwen embedding dimension")
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
                raise ValueError("Invalid embedding values")
            vector = vector[:self.settings.embedding_dimension]
            if not any(vector):
                raise ValueError("Zero embedding")
            return normalize(vector)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError("Qwen 임베딩 서버 응답을 확인할 수 없습니다.") from exc


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


def create_embedding_service(settings: Settings) -> EmbeddingService:
    return EmbeddingService(settings)


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
