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


@dataclass(frozen=True)
class DocumentChunkInput:
    chunk_index: int
    chunk_text: str
    page_number: Optional[int]
    section_title: Optional[str]
    char_count: int


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
