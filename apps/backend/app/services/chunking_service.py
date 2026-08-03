<<<<<<< HEAD
"""Split parsed documents into retrieval-sized chunks.

Paragraph boundaries are preferred so Korean and English text keeps its natural
structure; oversized paragraphs fall back to a character window with overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.services.document_parser import ParsedDocument

PARAGRAPH_SEPARATOR = re.compile(r"\n\s*\n")
WHITESPACE = re.compile(r"[ \t]+")
=======
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional, Protocol

from app.services.document_parser_service import ParsedDocument
>>>>>>> refs/remotes/origin/main


@dataclass(frozen=True)
class DocumentChunkInput:
<<<<<<< HEAD
=======
    course_id: str
    material_id: str
>>>>>>> refs/remotes/origin/main
    chunk_index: int
    chunk_text: str
    page_number: Optional[int]
    section_title: Optional[str]
    char_count: int


<<<<<<< HEAD
def create_chunks(
    document: ParsedDocument,
    *,
    chunk_size: int = 1000,
    chunk_overlap: int = 150,
    min_chunk_chars: int = 40,
) -> list[DocumentChunkInput]:
    """Return ordered chunks for one material, numbered from zero."""

    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[DocumentChunkInput] = []
    for page in document.pages:
        for text in _split_page(page.text, chunk_size, chunk_overlap):
            chunks.append(
                DocumentChunkInput(
                    chunk_index=len(chunks),
                    chunk_text=text,
                    page_number=page.page_number,
                    section_title=None,
                    char_count=len(text),
                )
            )

    return _reindex(_merge_short_chunks(chunks, min_chunk_chars))


def _split_page(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []

    pieces: list[str] = []
    buffer = ""
    for paragraph in PARAGRAPH_SEPARATOR.split(normalized):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > chunk_size:
            if buffer:
                pieces.append(buffer)
                buffer = ""
            pieces.extend(_split_by_characters(paragraph, chunk_size, chunk_overlap))
            continue

        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) > chunk_size:
            pieces.append(buffer)
            buffer = paragraph
        else:
            buffer = candidate

    if buffer:
        pieces.append(buffer)

    return [piece.strip() for piece in pieces if piece.strip()]


def _split_by_characters(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    step = max(1, chunk_size - chunk_overlap)
    pieces: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        pieces.append(text[start:end].strip())
        if end == len(text):
            break
        start += step

    return [piece for piece in pieces if piece]


def _merge_short_chunks(
    chunks: list[DocumentChunkInput],
    min_chunk_chars: int,
) -> list[DocumentChunkInput]:
    """Fold undersized chunks into the previous chunk of the same page."""

    if not chunks:
        return []

    merged: list[DocumentChunkInput] = []
    for chunk in chunks:
        previous = merged[-1] if merged else None
        is_short = chunk.char_count < min_chunk_chars
        can_merge = previous is not None and previous.page_number == chunk.page_number

        if is_short and can_merge:
            combined = f"{previous.chunk_text}\n\n{chunk.chunk_text}".strip()
            merged[-1] = DocumentChunkInput(
                chunk_index=previous.chunk_index,
                chunk_text=combined,
                page_number=previous.page_number,
                section_title=previous.section_title,
                char_count=len(combined),
            )
            continue

        merged.append(chunk)

    # A lone undersized chunk is still worth keeping; drop only empty leftovers.
    return [chunk for chunk in merged if chunk.chunk_text.strip()]


def _reindex(chunks: list[DocumentChunkInput]) -> list[DocumentChunkInput]:
    return [
        DocumentChunkInput(
            chunk_index=index,
            chunk_text=chunk.chunk_text,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            char_count=chunk.char_count,
        )
        for index, chunk in enumerate(chunks)
    ]


def _normalize(text: str) -> str:
    collapsed = WHITESPACE.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "\n".join(line.strip() for line in collapsed.split("\n")).strip()
=======
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
>>>>>>> refs/remotes/origin/main
