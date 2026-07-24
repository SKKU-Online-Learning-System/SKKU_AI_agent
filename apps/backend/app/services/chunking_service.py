from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional, Protocol

from app.services.document_parser_service import ParsedDocument


@dataclass(frozen=True)
class DocumentChunkInput:
    course_id: str
    material_id: str
    chunk_index: int
    chunk_text: str
    page_number: Optional[int]
    section_title: Optional[str]
    char_count: int


class ChunkingService(Protocol):
    def create_chunks(self, document: ParsedDocument) -> list[DocumentChunkInput]:
        raise NotImplementedError


class ParagraphChunkingService:
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        min_chunk_size: int = 100,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size")
        if min_chunk_size <= 0 or min_chunk_size > chunk_size:
            raise ValueError("min_chunk_size must be between 1 and chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def create_chunks(self, document: ParsedDocument) -> list[DocumentChunkInput]:
        chunks: list[DocumentChunkInput] = []
        for page in document.pages:
            page_text = self._normalize_text(page.text)
            if not page_text:
                continue
            for chunk_text in self._split_page(page_text):
                chunks.append(
                    DocumentChunkInput(
                        course_id=document.course_id,
                        material_id=document.material_id,
                        chunk_index=len(chunks),
                        chunk_text=chunk_text,
                        page_number=page.page_number,
                        section_title=None,
                        char_count=len(chunk_text),
                    )
                )
        return chunks

    def _split_page(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            maximum_end = min(start + self.chunk_size, len(text))
            end = maximum_end
            if maximum_end < len(text):
                paragraph_boundary = text.rfind(
                    "\n\n",
                    start + max(self.min_chunk_size, self.chunk_overlap + 1),
                    maximum_end + 1,
                )
                if paragraph_boundary >= 0:
                    end = paragraph_boundary

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + 1)

        if len(chunks) > 1 and len(chunks[-1]) < self.min_chunk_size:
            tail = chunks.pop()
            overlap = chunks[-1][-self.chunk_overlap :] if self.chunk_overlap else ""
            unique_tail = tail[len(overlap) :] if tail.startswith(overlap) else tail
            chunks[-1] = f"{chunks[-1]}{unique_tail}".strip()
        return chunks

    @staticmethod
    def _normalize_text(text: str) -> str:
        paragraphs = (
            re.sub(r"[ \t]+", " ", paragraph.strip())
            for paragraph in re.split(r"\n\s*\n", text)
        )
        return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
