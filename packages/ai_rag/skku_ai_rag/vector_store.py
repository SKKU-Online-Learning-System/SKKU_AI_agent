from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorRecord:
    id: str
    course_id: str
    material_id: str
    content: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    record: VectorRecord
    score: float


class VectorStore(Protocol):
    async def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    async def search(self, course_id: str, query_embedding: list[float], top_k: int) -> list[SearchHit]:
        raise NotImplementedError


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._records: dict[str, VectorRecord] = {}

    async def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = record

    async def search(self, course_id: str, query_embedding: list[float], top_k: int) -> list[SearchHit]:
        hits = [
            SearchHit(record=record, score=cosine_similarity(query_embedding, record.embedding))
            for record in self._records.values()
            if record.course_id == course_id
        ]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5

    if left_norm == 0 or right_norm == 0:
        return 0.0

    return dot / (left_norm * right_norm)
