"""A private index for a long PDF a student attached, so questions can read it.

A textbook is hundreds of pages; the text model's window holds a few. So a PDF
longer than ``ATTACHMENT_INLINE_MAX_PAGES`` is not read into the turn -- it is
indexed once, right after upload, the way course materials are (page text →
chunks → embeddings), and every question then pulls only the pages that match
it. The index belongs to the learner alone: it lives next to the file in their
own attachment directory, never in the course's vector store, so nothing a
student uploads can surface for anyone else.

Indexing runs in the background after the upload responds. A small status
file (``<file>.status.json``) says how far it is, so the composer can show
"색인 중 120/312쪽" and hold the question until the file is ready; the vectors
themselves sit in ``<file>.index.json``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

from app.core.config import Settings
from app.services.chunking_service import create_chunks
from app.services.document_parser import ParsedDocument, ParsedPage
from app.services.embedding_service import (
    EmbeddingError,
    cosine_similarity,
    create_embedding_service,
)

if TYPE_CHECKING:
    from app.services.voice.attachments import Attachment

log = logging.getLogger("voice.attachment-index")

STATUS_SUFFIX = ".status.json"
INDEX_SUFFIX = ".index.json"
# Progress is written every so many pages / chunks; each write is one small file.
PROGRESS_EVERY = 10
EMBED_BATCH = 16


@dataclass(frozen=True)
class Excerpt:
    page: int
    text: str
    score: float


def needs_index(attachment: "Attachment", settings: Settings) -> bool:
    """Whether this file is read through its index rather than whole."""
    return attachment.kind == "pdf" and attachment.pages > settings.attachment_inline_max_pages


def status_path(attachment: "Attachment") -> Path:
    return Path(attachment.path + STATUS_SUFFIX)


def index_path(attachment: "Attachment") -> Path:
    return Path(attachment.path + INDEX_SUFFIX)


def index_status(attachment: "Attachment") -> Optional[dict]:
    """The status record, or None when this file was never queued for indexing."""
    try:
        return json.loads(status_path(attachment).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_status(attachment: "Attachment", **fields) -> None:
    record = {"status": "indexing", "pages": attachment.pages, "pages_done": 0,
              "chunks": 0, "message": None, "updated_at": time.time()}
    record.update(fields)
    status_path(attachment).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def mark_indexing(attachment: "Attachment") -> dict:
    """Record that indexing is queued, so a status read right after upload says so."""
    _write_status(attachment)
    return index_status(attachment) or {}


def build_index(attachment: "Attachment", settings: Settings) -> None:
    """Extract, chunk and embed every page with text; runs off the request.

    Pages without a text layer are skipped rather than sent to the vision
    model: a scanned textbook would cost hundreds of vision calls, and the
    inline path (short PDFs) is where that budget is spent. A PDF with no text
    at all fails with a message that says so.
    """
    from app.services.voice.attachments import _pdf_pages

    path = Path(attachment.path)
    try:
        pages: list[ParsedPage] = []
        done = 0
        for number, text, _render in _pdf_pages(path, settings):
            if text.strip():
                pages.append(ParsedPage(page_number=number, text=text))
            done = number
            if done % PROGRESS_EVERY == 0:
                _write_status(attachment, pages_done=done)
        if not pages:
            _write_status(
                attachment, status="failed", pages_done=done,
                message="글자가 없는 PDF(스캔본)는 짧게 나눠 올려 주세요",
            )
            return

        document = ParsedDocument(
            material_id=attachment.id, course_id=attachment.course_id,
            title=attachment.name, pages=pages,
        )
        chunks = create_chunks(
            document,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            min_chunk_chars=settings.min_chunk_chars,
        )
        embedder = create_embedding_service(settings)
        limit = settings.embedding_max_chars
        records: list[dict] = []
        for start in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[start : start + EMBED_BATCH]
            vectors = embedder.embed_texts([chunk.chunk_text[:limit] for chunk in batch])
            for chunk, vector in zip(batch, vectors):
                records.append(
                    {"page": chunk.page_number or 0, "text": chunk.chunk_text, "embedding": vector}
                )
            _write_status(attachment, pages_done=attachment.pages, chunks=len(records))
        index_path(attachment).write_text(
            json.dumps(
                {
                    "embedding_model": embedder.model_name,
                    "pages": attachment.pages,
                    "pages_with_text": len(pages),
                    "chunks": records,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        _write_status(
            attachment, status="ready", pages_done=attachment.pages, chunks=len(records),
            pages_with_text=len(pages),
        )
        log.info(
            "attachment indexed name=%s pages=%d chunks=%d", attachment.name, attachment.pages,
            len(records),
        )
    except EmbeddingError as exc:
        log.warning("attachment index embedding failed name=%s: %s", attachment.name, exc)
        _write_status(attachment, status="failed", message="색인용 임베딩 서버를 사용할 수 없어요")
    except Exception:
        log.exception("attachment index failed name=%s", attachment.name)
        _write_status(attachment, status="failed", message="파일을 색인하지 못했어요")


def search_index(
    attachment: "Attachment",
    query: str,
    settings: Settings,
    *,
    top_k: Optional[int] = None,
) -> list[Excerpt]:
    """The chunks of the file that best match ``query``, ordered by page.

    With no query -- nothing typed yet that says what to look for -- the
    opening of the document is returned, so the model still knows what the
    file is.
    """
    top_k = top_k or settings.attachment_index_top_k
    try:
        index = json.loads(index_path(attachment).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EmbeddingError("ATTACHMENT_INDEX_MISSING") from exc
    chunks = [item for item in index.get("chunks", []) if isinstance(item, dict)]
    if not chunks:
        return []
    query = " ".join(query.split())
    if not query:
        picked = chunks[:top_k]
        return [Excerpt(int(c["page"]), str(c["text"]), 0.0) for c in picked]

    embedder = create_embedding_service(settings)
    query_vector = embedder.embed_text(query[: settings.embedding_max_chars])
    scored = _score(query_vector, chunks)
    best = sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
    best.sort(key=lambda item: (int(item[1]["page"]), item[1]["text"]))
    return [Excerpt(int(c["page"]), str(c["text"]), round(score, 4)) for score, c in best]


def _score(query_vector: Sequence[float], chunks: list[dict]) -> list[tuple[float, dict]]:
    try:
        import numpy as np

        matrix = np.asarray([c["embedding"] for c in chunks], dtype=np.float32)
        q = np.asarray(query_vector, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
        norms[norms == 0] = 1.0
        scores = (matrix @ q) / norms
        return [(float(score), chunk) for score, chunk in zip(scores, chunks)]
    except Exception:  # numpy absent or a malformed vector: the slow, safe path
        return [(cosine_similarity(query_vector, c.get("embedding") or []), c) for c in chunks]


def remove_index(attachment: "Attachment") -> None:
    status_path(attachment).unlink(missing_ok=True)
    index_path(attachment).unlink(missing_ok=True)
