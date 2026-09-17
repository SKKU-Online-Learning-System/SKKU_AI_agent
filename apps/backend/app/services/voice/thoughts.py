"""Headlines for the model's reasoning as it streams, the way Codex shows it.

The raw chain of thought is long, fast and in whatever language the model
picked; shown as it comes it reads as a wall of text that scrolls past before
anyone can read it. What a student can follow is a short line every few
seconds saying what the tutor is doing now -- "이름을 뜯어보며 접근을 정한다",
"시각 자료가 필요한지 따진다" -- which is what this module produces: it collects
the reasoning deltas of one model round and, once enough has arrived and
enough time has passed, asks the fast voice-profile model (thinking off) for
one Korean headline of the new part.

The summaries never gate the turn. They run as background tasks, one at a
time so they arrive in order, and whatever is still running when the round is
over is cancelled. A failure is logged and skipped; the raw reasoning still
reaches the screen as its own event.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from app.core.config import Settings
from app.services.llm_service import LLMError, LLMService

log = logging.getLogger("voice.thoughts")

TurnEventSink = Callable[[dict], Awaitable[None]]
# A closing flush summarizes what is left only when there is at least this
# much of it; a trailing "Let me finalize." is not worth a call.
FLUSH_MIN_CHARS = 120
MAX_HEADLINES = 12


class ThoughtSummarizer:
    """Turn one round's streamed reasoning into paced Korean headlines."""

    def __init__(
        self,
        *,
        llm: LLMService,
        settings: Settings,
        on_event: Optional[TurnEventSink],
        key: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.llm = llm
        self.settings = settings
        self.on_event = on_event
        self.key = key
        self.clock = clock
        self.headlines: list[str] = []
        self._pending: list[str] = []
        self._pending_chars = 0
        self._last_summary_at: float | None = None
        self._chain: asyncio.Task | None = None
        self._closed = False

    @property
    def enabled(self) -> bool:
        return (
            self.on_event is not None
            and self.settings.text_thought_summaries
            and not self._closed
        )

    def feed(self, delta: str) -> None:
        """Take one reasoning delta; start a summary when the pacing allows."""
        if not self.enabled or not delta:
            return
        self._pending.append(delta)
        self._pending_chars += len(delta)
        if self._pending_chars < self.settings.thought_summary_min_chars:
            return
        if (
            self._last_summary_at is not None
            and self.clock() - self._last_summary_at < self.settings.thought_summary_interval_seconds
        ):
            return
        if self._chain is not None and not self._chain.done():
            # One summary at a time, so headlines arrive in order.
            return
        self._start(self._take())

    def flush(self) -> None:
        """The reasoning ended (the answer began): summarize what is left, if enough."""
        if not self.enabled or self._pending_chars < FLUSH_MIN_CHARS:
            return
        if self._chain is not None and not self._chain.done():
            return
        self._start(self._take())

    async def close(self) -> None:
        """The round is over; nothing that is still running is worth waiting for."""
        self._closed = True
        if self._chain is not None and not self._chain.done():
            self._chain.cancel()
            await asyncio.gather(self._chain, return_exceptions=True)

    def _take(self) -> str:
        chunk = "".join(self._pending)
        self._pending = []
        self._pending_chars = 0
        self._last_summary_at = self.clock()
        return chunk

    def _start(self, chunk: str) -> None:
        self._chain = asyncio.create_task(self._summarize(chunk))

    async def _summarize(self, chunk: str) -> None:
        if len(self.headlines) >= MAX_HEADLINES:
            return
        try:
            headline = await self.llm.summarize_reasoning(
                previous=self.headlines[-4:], chunk=chunk
            )
        except LLMError as exc:
            log.debug("thought summary skipped: %s", exc)
            return
        except Exception:  # best effort: a headline must never cost the turn
            log.warning("thought summary failed", exc_info=True)
            return
        headline = _clean(headline)
        if not headline or headline in self.headlines[-3:]:
            return
        self.headlines.append(headline)
        if self.on_event is not None and not self._closed:
            await self.on_event({"type": "thought", "key": self.key, "text": headline})


def _clean(text: str) -> str:
    """One line, no quotes or trailing punctuation, bounded."""
    line = " ".join(text.strip().splitlines()[:1]).strip().strip('"\'“”「」')
    line = line.rstrip(".。!?！？ ").strip()
    if line.startswith("- "):
        line = line[2:]
    return line[:60]
