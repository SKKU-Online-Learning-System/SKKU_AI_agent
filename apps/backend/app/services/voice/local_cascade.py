"""Interruptible local cascade voice transport.

Browser PCM is endpointed by application-side Silero VAD, then sent to the
external Speech Server for ASR. The existing COURSE AGENT brain is reused with
the Qwen voice profile and the final text is synthesized by the external TTS
server. No model weight is loaded by this transport.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from app.core.config import Settings, get_settings
from app.services.model_server.speech_client import SpeechClient, SpeechError
from app.services.safety_service import NORMAL_RESULT, SafetyGuardService, SafetyResult
from app.services.voice.brain import StageTimer, VoiceContext, for_speech
from app.services.voice.local_brain import VoiceBrainResult, clone_context, think_voice
from app.services.voice.transport import (
    AgentAudio,
    AgentTextDelta,
    AgentTurnDone,
    Event,
    Failed,
    SessionReady,
    ToolCalled,
    Transcript,
    Transport,
    UserStartedSpeaking,
    UserStoppedSpeaking,
)
from app.services.voice.turn_detector import SAMPLE_RATE, TurnDetector

log = logging.getLogger("voice.local-cascade")
_SENTINEL = object()
_QUEUE_DONE = object()
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")
# Matches a *completed* sentence tail in a still-growing buffer. Unlike
# _SENTENCE_BOUNDARY this is used incrementally while the LLM streams, so it
# must only fire once the terminator is followed by whitespace.
_SENTENCE_FLUSH = re.compile(r"[.!?。！？]+[\"'”’)\]]*\s+|\n+")
# Where an early, mid-sentence release is safe. Each TTS request is generated
# independently, so joining two of them mid-phrase puts an F0, energy and phase
# discontinuity inside a word, which is audible as a click or chirp. A clause
# boundary already carries a pause and a pitch reset, so a seam there is not.
_CLAUSE_FLUSH = re.compile(r"[,;:、，；：]\s")
BrainRunner = Callable[..., Awaitable[VoiceBrainResult]]
QueuedEvent = tuple[int | None, Event]
# (text to synthesize, silence in ms to play after it)
TtsChunk = tuple[str, int]


def _split_long_segment(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current = ""
    for original_word in words:
        word = original_word
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = ""
        while len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(word[:max_chars])
            word = word[max_chars:]
        if word:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = word
    if current:
        chunks.append(current)
    return chunks


def _tts_chunks(
    text: str, max_chars: int, *, sentence_gap_ms: int, tail_gap_ms: int,
    min_chars: int = 0,
) -> list[TtsChunk]:
    """Prefer sentence-sized TTS requests and cap pathological long sentences.

    Each chunk carries the silence that belongs *after* it. The caller knows why
    it cut the stream where it did and passes that as ``tail_gap_ms``; every split
    made in here is a sentence or newline boundary, except the word-boundary
    splits inside an over-long sentence, which are mid-phrase and must not pause.
    """
    normalized = re.sub(r"[ \t]+", " ", text.strip())
    segments = [part.strip() for part in _SENTENCE_BOUNDARY.split(normalized) if part.strip()]
    if min_chars:
        # Splitting back at every sentence would undo the caller's floor and hand
        # the model a fragment too short to pitch. Merged sentences need no explicit
        # gap: inside one request the model renders the pause from the punctuation.
        merged: list[str] = []
        for segment in segments:
            if (
                merged
                and len(merged[-1]) < min_chars
                and len(merged[-1]) + 1 + len(segment) <= max_chars
            ):
                merged[-1] = f"{merged[-1]} {segment}"
            else:
                merged.append(segment)
        segments = merged
    chunks: list[TtsChunk] = []
    for index, segment in enumerate(segments):
        gap = tail_gap_ms if index == len(segments) - 1 else sentence_gap_ms
        pieces = (
            [segment] if len(segment) <= max_chars else _split_long_segment(segment, max_chars)
        )
        for offset, piece in enumerate(pieces):
            chunks.append((piece, gap if offset == len(pieces) - 1 else 0))
    return chunks or ([(normalized, tail_gap_ms)] if normalized else [])


def _pcm_duration_ms(pcm: bytes, sample_rate: int) -> int:
    if not sample_rate:
        return 0
    return round((len(pcm) / 2) * 1000 / sample_rate)


class _SpeechPipeline:
    """Turn a streaming LLM answer into audio without waiting for the full reply.

    Sentences are handed to the TTS server as soon as they complete, and each
    server-side PCM chunk is emitted the moment it arrives. A round that turns out
    to be a tool round is rolled back, so preamble text that never reaches the
    final reply is not spoken.
    """

    def __init__(
        self,
        *,
        transport: "LocalCascadeTransport",
        generation: int,
        first_chunk_max_chars: int,
        chunk_max_chars: int,
        first_chunk_hop_len: int,
        first_chunk_min_chars: int = 0,
        sentence_gap_ms: int = 0,
        clause_gap_ms: int = 0,
    ) -> None:
        self._transport = transport
        self._generation = generation
        self._first_chunk_max_chars = first_chunk_max_chars
        self._chunk_max_chars = chunk_max_chars
        self._first_chunk_hop_len = first_chunk_hop_len
        self._first_chunk_min_chars = first_chunk_min_chars
        self._sentence_gap_ms = sentence_gap_ms
        self._clause_gap_ms = clause_gap_ms
        # Shared by every TTS request of this turn so the server can level them
        # against each other. Per turn, not per session: a new turn starts from
        # the reference loudness again rather than inheriting an old one.
        self._continuity_id = uuid.uuid4().hex
        self._queue: asyncio.Queue[TtsChunk | object] = asyncio.Queue()
        self._pending = ""
        self._task: asyncio.Task[None] | None = None
        self._enqueued = 0
        self.chunks = 0
        self.audio_bytes = 0
        self.gap_bytes = 0
        self.sample_rate = 0
        self.first_audio_at: float | None = None
        self.started_at = 0.0

    # -- producer side -------------------------------------------------

    def start(self) -> None:
        self.started_at = time.perf_counter()
        self._task = asyncio.create_task(self._consume())

    def _enqueue(self, text: str, tail_gap_ms: int) -> None:
        chunks = _tts_chunks(
            text,
            self._next_limit(),
            sentence_gap_ms=self._sentence_gap_ms,
            tail_gap_ms=tail_gap_ms,
            min_chars=self._first_chunk_min_chars if self._enqueued == 0 else 0,
        )
        for chunk in chunks:
            self._queue.put_nowait(chunk)
            self._enqueued += 1

    def _next_limit(self) -> int:
        return self._first_chunk_max_chars if self._enqueued == 0 else self._chunk_max_chars

    async def feed(self, token: str) -> None:
        """Accumulate streamed answer text and release completed sentences."""
        self._pending += token
        while True:
            # The opening chunk has a floor, whichever boundary ends it. The floor
            # was only enforced on the clause path below, so a reply starting
            # "안녕하세요! ..." still made a 6-character first request -- and "네!"
            # a 2-character one, which is 204ms of audio when the packet after it
            # cannot arrive for ~650ms (the LLM needs ~450ms to finish the next
            # sentence and the TTS server ~200ms for its first packet). Measured
            # over 24 such turns, 7 came out too short to cover that, so playback
            # stalled right after the greeting.
            #
            # This does NOT make the greeting's pitch match the answer. That gap
            # is the model reading the "!": "안녕하세요!" comes back at 169Hz against
            # 115Hz for "안녕하세요.", and it stays at 172Hz even when embedded in one
            # long request, so merging it changes nothing there (n=24, p=0.98).
            # The floor is here for the buffer, not for the register.
            #
            # Searching from the floor rolls the short opener into the sentence
            # after it rather than holding it back, which costs ~450ms of first
            # audio on these replies and nothing on any other.
            floor = self._first_chunk_min_chars if self._enqueued == 0 else 0
            match = next(
                (m for m in _SENTENCE_FLUSH.finditer(self._pending) if m.end() >= floor),
                None,
            )
            if match is None:
                break
            sentence = self._pending[: match.end()].strip()
            self._pending = self._pending[match.end() :]
            if sentence:
                self._enqueue(sentence, self._sentence_gap_ms)
        # The opening chunk may be released before its sentence ends, but only at a
        # clause boundary. Splitting at an arbitrary word boundary saves a little
        # more latency and sounds broken; if the sentence has no clause boundary,
        # the sentence flush above handles it.
        if self._enqueued == 0 and self._first_chunk_min_chars:
            match = _CLAUSE_FLUSH.search(self._pending, self._first_chunk_min_chars)
            if match is not None:
                head = self._pending[: match.end()].strip()
                self._pending = self._pending[match.end() :]
                if head:
                    self._enqueue(head, self._clause_gap_ms)
        # A sentence that never terminates must not stall playback forever.
        if len(self._pending) > self._chunk_max_chars * 2:
            head = _split_long_segment(self._pending, self._next_limit())
            self._pending = head.pop() if head else ""
            for piece in head:
                # A word-boundary split lands mid-phrase; pausing there sounds
                # like a stall rather than a breath.
                self._queue.put_nowait((piece, 0))
                self._enqueued += 1

    async def rollback(self) -> None:
        """Discard text from a round that turned out to be a tool round."""
        self._pending = ""
        dropped = 0
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is _QUEUE_DONE:
                self._queue.put_nowait(item)
                break
            dropped += 1
        self._enqueued = max(0, self._enqueued - dropped)
        if dropped or self.chunks:
            log.info(
                "voice tts rollback generation=%d dropped_chunks=%d already_spoken=%d",
                self._generation,
                dropped,
                self.chunks,
            )

    async def finish(self, reply: str) -> None:
        """Flush the tail, backfill if nothing streamed, then drain the queue."""
        tail = self._pending.strip()
        self._pending = ""
        if tail:
            self._enqueue(tail, 0)
        if self._enqueued == 0 and reply.strip():
            # Non-streaming providers (and the mock) never call feed(); fall back
            # to synthesizing the finished reply.
            self._enqueue(reply, 0)
        self._queue.put_nowait(_QUEUE_DONE)
        if self._task is not None:
            await self._task

    async def abort(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        # gather() also retrieves an already-stored exception, which keeps a failed
        # consumer from surfacing as "task exception was never retrieved".
        await asyncio.gather(task, return_exceptions=True)

    # -- consumer side -------------------------------------------------

    async def _emit_gap(self, gap_ms: int) -> None:
        """Play the pause the previous request's boundary lost."""
        samples = round(self.sample_rate * gap_ms / 1000)
        if samples <= 0:
            return
        silence = b"\x00\x00" * samples
        self.gap_bytes += len(silence)
        await self._transport._emit(
            AgentAudio(silence, rate=self.sample_rate), self._generation
        )

    async def _consume(self) -> None:
        transport = self._transport
        done = False
        pending_gap_ms = 0
        while not done:
            item = await self._queue.get()
            if item is _QUEUE_DONE:
                return
            if not transport._current(self._generation):
                return
            # Every request pays the TTS server's fixed first-packet cost, so once
            # the first chunk is out the way, merge whatever the LLM has produced
            # in the meantime into a single request instead of paying it again.
            # Merged-away boundaries need no explicit pause: inside one request the
            # model renders them from the punctuation itself. Only the last part's
            # gap survives, because only that boundary becomes a request seam.
            text, gap_ms = item  # type: ignore[misc]
            parts = [text]
            if self.chunks > 0:
                budget = self._chunk_max_chars * 3
                while sum(len(part) for part in parts) < budget:
                    try:
                        extra = self._queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if extra is _QUEUE_DONE:
                        done = True
                        break
                    extra_text, gap_ms = extra  # type: ignore[misc]
                    parts.append(extra_text)
            # URLs belong on screen, not in speech.
            chunk = for_speech(" ".join(parts)).strip()
            if not chunk:
                continue
            # Emitted before the request, not after the previous one: the pause is
            # then already scheduled in the player while this request is still being
            # synthesized, so it doubles as a jitter buffer instead of adding delay.
            if pending_gap_ms and self.sample_rate:
                await self._emit_gap(pending_gap_ms)
                if not transport._current(self._generation):
                    return
            pending_gap_ms = gap_ms
            chunk_started = time.perf_counter()
            chunk_bytes = 0
            async for pcm, rate in transport.speech.synthesize_stream(
                chunk,
                speaker=transport.settings.tts_speaker,
                language="Korean",
                hop_len=self._first_chunk_hop_len if self.chunks == 0 else None,
                continuity_id=self._continuity_id,
            ):
                if not transport._current(self._generation):
                    return
                if self.first_audio_at is None:
                    self.first_audio_at = time.perf_counter()
                self.sample_rate = rate
                self.audio_bytes += len(pcm)
                chunk_bytes += len(pcm)
                await transport._emit(AgentAudio(pcm, rate=rate), self._generation)
            self.chunks += 1
            log.info(
                "local voice tts chunk generation=%d index=%d chars=%d wall_ms=%d audio_ms=%d",
                self._generation,
                self.chunks,
                len(chunk),
                round((time.perf_counter() - chunk_started) * 1000),
                round((chunk_bytes / 2) * 1000 / (self.sample_rate or 24000)),
            )

    @property
    def audio_duration_ms(self) -> int:
        """Synthesized speech only; inserted silence is excluded to keep RTF honest."""
        if not self.sample_rate:
            return 0
        return round((self.audio_bytes / 2) * 1000 / self.sample_rate)

    @property
    def gap_duration_ms(self) -> int:
        if not self.sample_rate:
            return 0
        return round((self.gap_bytes / 2) * 1000 / self.sample_rate)


class LocalCascadeTransport(Transport):
    """ASR -> existing COURSE AGENT brain -> chunked TTS with generation cancellation."""

    name = "local_cascade"
    provider_name = "local_qwen"

    def __init__(
        self,
        *,
        context: VoiceContext,
        mode: str,
        settings: Settings | None = None,
        speech_client: SpeechClient | None = None,
        detector: TurnDetector | None = None,
        brain_runner: BrainRunner = think_voice,
        safety_service: SafetyGuardService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.context = context
        self._brain_context = clone_context(context)
        self.mode = mode
        self.speech = speech_client or SpeechClient(self.settings)
        self.detector = detector or TurnDetector()
        self.brain_runner = brain_runner
        self.safety = safety_service or SafetyGuardService()
        self.model_name = self.settings.voice_llm_model
        self.last_web_sources: list[str] = []
        self.last_safety: SafetyResult = NORMAL_RESULT
        self._events: asyncio.Queue[QueuedEvent | object] = asyncio.Queue()
        self._generation = 0
        self._active_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        if self._closed:
            raise RuntimeError("voice transport is closed")
        await self._events.put((None, SessionReady()))

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed:
            return
        was_speaking = self.detector.speaking
        utterance = self.detector.feed(pcm)
        if not was_speaking and self.detector.speaking:
            generation = await self._begin_generation()
            log.info("voice barge-in/start generation=%d", generation)
            await self._emit(UserStartedSpeaking(), generation)
        if utterance is None:
            return
        generation = self._generation
        await self._emit(UserStoppedSpeaking(), generation)
        speech_end = time.perf_counter()
        self._active_task = asyncio.create_task(
            self._run_audio_turn(utterance, generation, speech_end)
        )

    async def send_text(self, text: str) -> None:
        if self._closed:
            return
        text = text.strip()
        if not text:
            return
        generation = await self._begin_generation()
        await self._emit(UserStoppedSpeaking(), generation)
        started = time.perf_counter()
        self._active_task = asyncio.create_task(
            self._run_text_turn(text, generation, started, vad_speech_ms=0, asr_ms=0)
        )

    async def _begin_generation(self) -> int:
        self._generation += 1
        task = self._active_task
        self._active_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.last_web_sources = []
        self.last_safety = NORMAL_RESULT
        return self._generation

    async def _run_audio_turn(
        self,
        utterance: bytes,
        generation: int,
        speech_end: float,
    ) -> None:
        vad_speech_ms = round(len(utterance) / 2 / SAMPLE_RATE * 1000)
        asr_started = time.perf_counter()
        try:
            result = await self.speech.transcribe(utterance, sample_rate=SAMPLE_RATE)
        except asyncio.CancelledError:
            raise
        except SpeechError:
            asr_ms = round((time.perf_counter() - asr_started) * 1000)
            self._log_metrics(
                vad_speech_ms=vad_speech_ms,
                asr_ms=asr_ms,
                llm_ttft_ms=0,
                llm_total_ms=0,
                tts_ms=0,
                speech_end_to_first_audio_ms=0,
                total_turn_ms=asr_ms,
                status="asr_failed",
            )
            await self._fail("음성 인식 서버를 사용할 수 없습니다.", generation)
            return
        asr_ms = round((time.perf_counter() - asr_started) * 1000)
        await self._run_text_turn(
            result.text,
            generation,
            speech_end,
            vad_speech_ms=vad_speech_ms,
            asr_ms=asr_ms,
        )

    async def _run_text_turn(
        self,
        transcript: str,
        generation: int,
        speech_end: float,
        *,
        vad_speech_ms: int,
        asr_ms: int,
    ) -> None:
        turn_started = time.perf_counter()
        timer = StageTimer()
        if not self._current(generation):
            return
        safety = self.safety.check_question(transcript)
        self.last_safety = safety
        await self._emit(
            Transcript("user", transcript, item_id=f"local-{generation}-user"), generation
        )

        speech = _SpeechPipeline(
            transport=self,
            generation=generation,
            first_chunk_max_chars=self.settings.tts_first_chunk_max_chars,
            chunk_max_chars=self.settings.tts_chunk_max_chars,
            first_chunk_hop_len=self.settings.tts_first_chunk_hop_len,
            first_chunk_min_chars=self.settings.tts_first_chunk_min_chars,
            sentence_gap_ms=self.settings.tts_sentence_gap_ms,
            clause_gap_ms=self.settings.tts_clause_gap_ms,
        )
        speech.start()

        def metrics(status: str) -> None:
            self._log_metrics(
                vad_speech_ms=vad_speech_ms,
                asr_ms=asr_ms,
                llm_ttft_ms=timer.timings_ms.get("llm_ttft", 0),
                llm_total_ms=timer.timings_ms.get("llm", 0),
                tts_ms=round((time.perf_counter() - speech.started_at) * 1000),
                tts_audio_duration_ms=speech.audio_duration_ms,
                tts_gap_ms=speech.gap_duration_ms,
                tts_chunks=speech.chunks,
                speech_end_to_first_audio_ms=(
                    round((speech.first_audio_at - speech_end) * 1000)
                    if speech.first_audio_at
                    else 0
                ),
                total_turn_ms=round((time.perf_counter() - turn_started) * 1000),
                status=status,
            )

        try:
            if safety.blocked:
                reply = safety.safe_answer or "요청하신 내용은 도와드릴 수 없습니다."
                self._brain_context.append_history({"role": "user", "content": transcript})
                self._brain_context.append_history({"role": "assistant", "content": reply})
                self._brain_context.last_material_sources = []
                await self._emit(AgentTextDelta(reply), generation)
                brain_result = VoiceBrainResult(
                    reply=reply,
                    tools=[],
                    sources=[],
                    visualizations=[],
                    model_name=self.model_name,
                )
            else:
                brain_result = await self.brain_runner(
                    self._brain_context,
                    transcript,
                    timer,
                    self.mode,
                    on_token=lambda token: self._emit(AgentTextDelta(token), generation),
                    on_speech_delta=speech.feed,
                    on_speech_rollback=speech.rollback,
                )
                reply = brain_result.reply
                self.model_name = brain_result.model_name or self.model_name
        except asyncio.CancelledError:
            await speech.abort()
            raise
        except Exception:
            log.exception("local voice LLM turn failed")
            await speech.abort()
            metrics("llm_failed")
            await self._fail("Voice LLM 서버가 응답을 생성하지 못했습니다.", generation)
            return

        if not self._current(generation):
            await speech.abort()
            return
        self.context.last_material_sources = list(self._brain_context.last_material_sources)
        self.last_web_sources = list(brain_result.sources[:3])
        for name in brain_result.tools:
            if name == "show_visualization":
                continue
            result = {"sources": self.last_web_sources} if name == "search_trusted_web" else None
            await self._emit(ToolCalled(name=name, result=result), generation)
        for visualization in brain_result.visualizations:
            await self._emit(
                ToolCalled(name="show_visualization", result=visualization), generation
            )
        await self._emit(
            Transcript("agent", reply, item_id=f"local-{generation}-agent"), generation
        )

        try:
            await speech.finish(reply)
        except asyncio.CancelledError:
            await speech.abort()
            raise
        except SpeechError:
            await speech.abort()
            metrics("tts_failed")
            await self._fail("음성 합성 서버가 응답 오디오를 생성하지 못했습니다.", generation)
            return

        if not self._current(generation):
            return
        await self._emit(AgentTurnDone(), generation)
        metrics("ok")

    def _log_metrics(
        self,
        *,
        vad_speech_ms: int,
        asr_ms: int,
        llm_ttft_ms: int,
        llm_total_ms: int,
        tts_ms: int,
        speech_end_to_first_audio_ms: int,
        total_turn_ms: int,
        status: str,
        tts_audio_duration_ms: int = 0,
        tts_gap_ms: int = 0,
        tts_chunks: int = 0,
    ) -> None:
        # Streaming responses carry no X-Inference-Ms header, so RTF is measured
        # against the wall time the transport actually spent on synthesis.
        tts_rtf = (
            round(tts_ms / tts_audio_duration_ms, 4) if tts_audio_duration_ms > 0 else None
        )
        log.info(
            "local voice turn status=%s metrics=%s",
            status,
            {
                "vad_speech_ms": vad_speech_ms,
                "asr_ms": asr_ms,
                "llm_ttft_ms": llm_ttft_ms,
                "llm_total_ms": llm_total_ms,
                "tts_ms": tts_ms,
                "tts_audio_duration_ms": tts_audio_duration_ms,
                "tts_gap_ms": tts_gap_ms,
                "tts_rtf": tts_rtf,
                "tts_chunks": tts_chunks,
                "speech_end_to_first_audio_ms": speech_end_to_first_audio_ms,
                "total_turn_ms": total_turn_ms,
            },
        )

    async def _fail(self, message: str, generation: int) -> None:
        await self._emit(Failed(message, fatal=False), generation)

    async def _emit(self, event: Event, generation: int) -> None:
        if self._current(generation):
            await self._events.put((generation, event))

    def _current(self, generation: int) -> bool:
        return not self._closed and generation == self._generation

    async def events(self) -> AsyncIterator[Event]:
        while True:
            item = await self._events.get()
            if item is _SENTINEL:
                break
            generation, event = item  # type: ignore[misc]
            if generation is not None and not self._current(generation):
                continue
            yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        task = self._active_task
        self._active_task = None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._events.put(_SENTINEL)
