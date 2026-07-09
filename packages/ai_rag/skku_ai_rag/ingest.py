from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from skku_ai_rag.embeddings import EmbeddingProvider
from skku_ai_rag.vector_store import VectorRecord, VectorStore


@dataclass(frozen=True)
class DocumentInput:
    course_id: str
    material_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class IngestionPipeline:
    def __init__(self, vector_store: VectorStore, embedding_provider: EmbeddingProvider) -> None:
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider

    async def ingest(self, document: DocumentInput) -> list[VectorRecord]:
        chunks = split_text_by_words(document.text)
        embeddings = await self.embedding_provider.embed(chunks)
        records = [
            VectorRecord(
                id=str(uuid4()),
                course_id=document.course_id,
                material_id=document.material_id,
                content=chunk,
                embedding=embedding,
                metadata={**document.metadata, "chunkIndex": index},
            )
            for index, (chunk, embedding) in enumerate(zip(chunks, embeddings))
        ]

        await self.vector_store.upsert(records)
        return records


def split_text_by_words(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    words = text.split()
    if not words:
        return []

    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step

    return chunks
