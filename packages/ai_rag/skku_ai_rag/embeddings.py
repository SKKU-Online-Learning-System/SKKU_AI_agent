from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Protocol

from skku_ai_rag.config import RagConfig


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class OpenAIEmbeddingProvider:
    def __init__(self, config: RagConfig) -> None:
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings.")

        from openai import AsyncOpenAI

        self.config = config
        self.client = AsyncOpenAI(api_key=config.openai_api_key)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self.client.embeddings.create(
            model=self.config.embedding_model,
            input=list(texts),
        )
        return [item.embedding for item in response.data]


class LocalHashEmbeddingProvider:
    """Deterministic local embedding provider for smoke tests and offline development."""

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        words = re.findall(r"[0-9a-zA-Z가-힣]+", text.lower())
        tokens = [f"word:{word}" for word in words]
        tokens.extend(
            f"char:{word[index:index + size]}"
            for word in words
            for size in (2, 3)
            for index in range(len(word) - size + 1)
        )

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        magnitude = sum(value * value for value in vector) ** 0.5
        if magnitude == 0:
            return vector

        return [value / magnitude for value in vector]
