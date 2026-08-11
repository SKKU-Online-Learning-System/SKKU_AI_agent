"""Extracted text must be storable: PostgreSQL rejects NUL in text columns.

These target `app.services.document_parser`, the module the processing pipeline
actually calls. `document_parser_service` is an older, unused duplicate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.chunking_service import create_chunks
from app.services.document_parser import (
    EmptyDocumentError,
    parse_material,
    sanitize_text,
)


def _parse(path: Path):
    return parse_material(
        material_id="material-1",
        course_id="course-1",
        title="lecture.txt",
        storage_path=path,
    )


def test_sanitize_text_drops_control_characters_but_keeps_layout() -> None:
    assert sanitize_text("Transformer\x00 Network\x0b\x1f") == "Transformer Network"
    assert sanitize_text("첫 줄\n\t들여쓰기\r\n") == "첫 줄\n\t들여쓰기\r\n"


def test_parsed_pages_are_free_of_nul_bytes(tmp_path: Path) -> None:
    path = tmp_path / "lecture.txt"
    path.write_text("Transformer Network\x00 (Part 2)\n\n\x00Self-Attention", encoding="utf-8")

    document = _parse(path)

    assert "\x00" not in document.full_text
    assert all("\x00" not in page.text for page in document.pages)
    assert "Transformer Network (Part 2)" in document.full_text


def test_pages_that_only_held_control_characters_are_dropped(tmp_path: Path) -> None:
    path = tmp_path / "lecture.txt"
    path.write_text("\x00\x0c real content", encoding="utf-8")

    document = _parse(path)

    assert document.full_text.strip() == "real content"


def test_chunks_built_from_a_dirty_document_are_insertable(tmp_path: Path) -> None:
    """The failing INSERT was on `document_chunks.chunk_text`, so assert there."""

    path = tmp_path / "lecture.txt"
    path.write_text(
        "\n\n".join(f"슬라이드 {index}\x00 본문 내용입니다." for index in range(1, 12)),
        encoding="utf-8",
    )

    chunks = create_chunks(_parse(path), chunk_size=200, chunk_overlap=40, min_chunk_chars=10)

    assert chunks
    assert all("\x00" not in chunk.chunk_text for chunk in chunks)


def test_a_document_of_only_control_characters_fails_with_a_clear_code(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lecture.txt"
    path.write_text("\x00\x00\x0c", encoding="utf-8")

    with pytest.raises(EmptyDocumentError):
        _parse(path)
