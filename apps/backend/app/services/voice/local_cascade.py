"""Interruptible local cascade voice transport.

Browser PCM is endpointed by application-side Silero VAD, then sent to the
external Speech Server for ASR. The existing COURSE AGENT brain is reused with
the Qwen voice profile and the final text is synthesized by the external TTS
server. No model weight is loaded by this transport.

The brain releases one validated utterance per turn (see ``local_brain``), and
its visual clue with it, so this transport synthesizes a *finished* reply and
shows the clue before speaking it. It still splits that reply into
several TTS requests and forwards each server chunk as it arrives, so the
student hears the opening while the rest is still being synthesized.
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
from app.services.voice.brain import (
    StageTimer,
    VoiceContext,
    for_speech,
    last_assistant_turn,
)
from app.services.voice.filler import pick_filler
from app.services.voice.local_brain import VoiceBrainResult, think_voice
from app.services.voice.transport import (
    AgentAudio,
    AgentFiller,
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
# Where an early, mid-sentence cut is safe. Each TTS request is generated
# independently, so joining two of them mid-phrase puts an F0, energy and phase
# discontinuity inside a word, which is audible as a click or chirp. A clause
# boundary already carries a pause and a pitch reset, so a seam there is not.
_CLAUSE_BOUNDARY = re.compile(r"[,;:、，；：]\s")
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


def _opening_pieces(segment: str, max_chars: int, clause_gap_ms: int) -> list[TtsChunk]:
    """Cut an opening sentence that exceeds the first-request limit.

    Do not expect a latency win from cutting harder: token2wav costs roughly
    600ms almost regardless of token count on this backend, which is why
    ``tts_first_chunk_max_chars`` is neutral by default. This only decides
    *where* an over-long opening is cut, and a clause boundary is the one place
    a seam is inaudible. The gap on the last piece is a placeholder the caller
    replaces with whatever boundary actually follows the sentence.
    """
    if len(segment) <= max_chars:
        return [(segment, 0)]
    matches = list(_CLAUSE_BOUNDARY.finditer(segment[: max_chars + 1]))
    if matches:
        head = segment[: matches[-1].end()].strip()
        tail = segment[matches[-1].end() :].strip()
        if head and tail:
            rest = [tail] if len(tail) <= max_chars else _split_long_segment(tail, max_chars)
            return [(head, clause_gap_ms), *[(piece, 0) for piece in rest]]
    # A word-boundary split lands mid-phrase; pausing there sounds like a stall
    # rather than a breath, so those seams carry no gap.
    return [(piece, 0) for piece in _split_long_segment(segment, max_chars)]


def _tts_chunks(
    text: str,
    *,
    first_max_chars: int,
    max_chars: int,
    min_chars: int = 0,
    sentence_gap_ms: int = 0,
    clause_gap_ms: int = 0,
) -> list[TtsChunk]:
    """Plan the TTS requests for one finished reply.

    Each chunk carries the silence that belongs *after* it, because a seam
    between two independently generated requests loses the pause the punctuation
    would otherwise have produced. The final chunk ends the turn, so it needs no
    trailing silence.
    """
    normalized = re.sub(r"[ \t]+", " ", text.strip())
    if not normalized:
        return []
    segments = [part.strip() for part in _SENTENCE_BOUNDARY.split(normalized) if part.strip()]
    if not segments:
        segments = [normalized]
    if min_chars:
        # A sentence too short to pitch makes a request whose audio cannot cover
        # the synthesis of the request after it, so playback stalls right after
        # it. Merged sentences need no explicit gap: inside one request the model
        # renders the pause from the punctuation itself.
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
        trailing_gap = 0 if index == len(segments) - 1 else sentence_gap_ms
        if index == 0:
            pieces = _opening_pieces(segment, first_max_chars, clause_gap_ms)
        elif len(segment) <= max_chars:
            pieces = [(segment, 0)]
        else:
            pieces = [(piece, 0) for piece in _split_long_segment(segment, max_chars)]
        if not pieces:
            continue
        pieces[-1] = (pieces[-1][0], trailing_gap)
        chunks.extend(pieces)
    return chunks


class _FillerSpeech:
    """Speak a fixed progress notice, but only while the model is still working.

    The whole reply is validated before any of it is released, so a slow turn is
    silence the student cannot interpret. This starts synthesizing the notice the
    moment the turn does, concurrently with the brain, and decides whether to play
    it when its first audio is ready:

    * reply already ready -> drop it unheard. A spoken filler always delays the
      answer behind it, so it must only buy back dead air that actually happened.
    * still thinking -> commit to the whole notice. Cutting synthesized speech
      mid-word sounds broken, so there is no half-played filler.
    """

    def __init__(self, *, transport: "LocalCascadeTransport", generation: int, text: str) -> None:
        self._transport = transport
        self._generation = generation
        self._text = text
        self._reply_ready = False
        self._task: asyncio.Task[None] | None = None
        self.spoke = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def reply_ready(self) -> None:
        """Close the window the moment the reply exists, not when we get round to it.

        Several events are emitted between the brain returning and settle(); without
        this the notice could still commit itself during them and delay an answer
        that was already finished.
        """
        self._reply_ready = True

    async def _run(self) -> None:
        transport = self._transport
        try:
            async for pcm, rate in transport.speech.synthesize_stream(
                self._text,
                speaker=transport.settings.tts_speaker,
                language="Korean",
            ):
                if not transport._current(self._generation):
                    return
                if not self.spoke:
                    # Checked and set without awaiting in between, so settle()
                    # can never observe a half-made decision.
                    if self._reply_ready:
                        return
                    self.spoke = True
                await transport._emit(
                    AgentAudio(pcm, rate=rate, filler=True), self._generation
                )
        except asyncio.CancelledError:
            raise
        except SpeechError:
            # The notice is a courtesy; losing it must not cost the answer.
            log.warning("voice filler synthesis failed; continuing without it")

    async def settle(self) -> None:
        """Finish or drop the notice before any answer audio is emitted.

        Ordering matters: audio plays in the order the client receives it, so the
        notice has to be entirely out before the reply starts, or the two
        interleave into nonsense. Only for the path that is about to speak a reply.
        """
        self._reply_ready = True
        task = self._task
        self._task = None
        if task is None:
            return
        if not self.spoke and not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def abort(self) -> None:
        """Drop the notice now, without waiting for it to finish speaking.

        Barge-in awaits the cancelled turn, so this must not block on the rest of
        a synthesis request: waiting for a committed notice to play out would make
        interrupting the agent feel unresponsive. Nothing is going to be spoken
        after this, so there is no ordering left to protect.
        """
        self._reply_ready = True
        task = self._task
        self._task = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


class _SpeechPipeline:
    """Synthesize a finished reply as several requests, emitting audio as it arrives.

    The reply is planned into chunks up front; the consumer issues one request at
    a time and forwards every server-side PCM chunk immediately, so the opening
    plays while the rest is still being synthesized. A cancelled generation stops
    the consumer between chunks and mid-stream.
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
        self._task: asyncio.Task[None] | None = None
        self.chunks = 0
        self.audio_bytes = 0
        self.gap_bytes = 0
        self.sample_rate = 0
        self.first_audio_at: float | None = None
        # Wall time spent inside synthesis requests, and nothing else, so the
        # logged RTF stays comparable across turns of different LLM latency.
        self.synthesis_ms = 0

    # -- producer side -------------------------------------------------

    def plan(self, reply: str) -> list[TtsChunk]:
        return _tts_chunks(
            for_speech(reply),
            first_max_chars=self._first_chunk_max_chars,
            max_chars=self._chunk_max_chars,
            min_chars=self._first_chunk_min_chars,
            sentence_gap_ms=self._sentence_gap_ms,
            clause_gap_ms=self._clause_gap_ms,
        )

    async def speak(self, reply: str) -> None:
        """Synthesize one finished reply and return when its audio is emitted."""
        chunks = self.plan(reply)
        if not chunks:
            return
        for chunk in chunks:
            self._queue.put_nowait(chunk)
        self._queue.put_nowait(_QUEUE_DONE)
        self._task = asyncio.create_task(self._consume())
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
        await self._transport._emit(AgentAudio(silence, rate=self.sample_rate), self._generation)

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
            # the first chunk is out the way, merge the rest into a single request
            # instead of paying it again. Merged-away boundaries need no explicit
            # pause: inside one request the model renders them from the punctuation
            # itself. Only the last part's gap survives, because only that boundary
            # becomes a request seam.
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
            chunk = " ".join(parts).strip()
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
            try:
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
            finally:
                self.synthesis_ms += round((time.perf_counter() - chunk_started) * 1000)
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
    # The brain runs against the session context directly, so the route must not
    # also write the conversation from the transcript events it relays.
    owns_history = True

    def __init__(
        self,
        *,
        context: VoiceContext,
        settings: Settings | None = None,
        speech_client: SpeechClient | None = None,
        detector: TurnDetector | None = None,
        brain_runner: BrainRunner = think_voice,
        safety_service: SafetyGuardService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.context = context
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
        if self._active_task is not None and not self._active_task.done():
            # Speech onset already claimed a generation, so normally nothing is
            # running here. A typed turn submitted *while* this utterance was
            # still being spoken claims one after it, though, and would then keep
            # answering into the same generation as this one: two turns, one
            # playback stream, their audio interleaved and both logged. The
            # utterance the student just finished is the newer intent, so it
            # supersedes that turn the way any other new turn would.
            generation = await self._begin_generation()
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
                llm_total_ms=0,
                tts_ms=0,
                speech_end_to_first_audio_ms=0,
                total_turn_ms=asr_ms,
                status="asr_failed",
            )
            await self._fail("음성을 알아듣지 못했어요. 잠시 후 다시 말씀해 주세요.", generation)
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
        filler: _FillerSpeech | None = None
        notice = None
        if not safety.blocked:
            # A blocked answer is already written, so there is nothing to wait for;
            # a greeting or an acknowledgement is not waiting for one either.
            notice = pick_filler(
                transcript,
                history_length=len(self.context.history),
                previous=self.context.last_filler,
                previous_turn=last_assistant_turn(self.context),
            )
        if notice:
            self.context.last_filler = notice
            await self._emit(AgentFiller(notice, transient=True), generation)
            if self.settings.voice_spoken_filler:
                filler = _FillerSpeech(
                    transport=self, generation=generation, text=for_speech(notice)
                )
                filler.start()

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

        taught: dict = {}

        def metrics(status: str) -> None:
            self._log_metrics(
                student_state=taught.get("student_state", ""),
                hint_level=taught.get("hint_level", self.context.hint_level),
                vad_speech_ms=vad_speech_ms,
                asr_ms=asr_ms,
                llm_total_ms=timer.timings_ms.get("llm", 0),
                tts_ms=speech.synthesis_ms,
                tts_audio_duration_ms=speech.audio_duration_ms,
                tts_gap_ms=speech.gap_duration_ms,
                tts_chunks=speech.chunks,
                filler_spoken=filler is not None and filler.spoke,
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
                self.context.append_history({"role": "user", "content": transcript})
                self.context.append_history({"role": "assistant", "content": reply})
                self.context.last_material_sources = []
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
                    self.context,
                    transcript,
                    timer,
                    on_token=lambda token: self._emit(AgentTextDelta(token), generation),
                )
                if filler is not None:
                    filler.reply_ready()
                taught.update(
                    student_state=brain_result.student_state, hint_level=brain_result.hint_level
                )
                reply = brain_result.reply
                self.model_name = brain_result.model_name or self.model_name
        except asyncio.CancelledError:
            await _drop_filler(filler)
            await speech.abort()
            raise
        except Exception:
            log.exception("local voice LLM turn failed")
            await _drop_filler(filler)
            await speech.abort()
            metrics("llm_failed")
            await self._fail("답변을 만들지 못했어요. 잠시 후 다시 질문해 주세요.", generation)
            return

        if not self._current(generation):
            await _drop_filler(filler)
            await speech.abort()
            return
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
            # The notice has to be fully out, or dropped, before the reply's audio.
            # Inside the try so that being cancelled here still tears down the
            # visualization worker with everything else.
            await _finish_filler(filler)
            await speech.speak(reply)
        except asyncio.CancelledError:
            await speech.abort()
            raise
        except SpeechError:
            await speech.abort()
            metrics("tts_failed")
            await self._fail("답변을 읽어 드리지 못했어요. 화면의 글로 확인해 주세요.", generation)
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
        llm_total_ms: int,
        tts_ms: int,
        speech_end_to_first_audio_ms: int,
        total_turn_ms: int,
        status: str,
        tts_audio_duration_ms: int = 0,
        tts_gap_ms: int = 0,
        tts_chunks: int = 0,
        filler_spoken: bool = False,
        student_state: str = "",
        hint_level: int = 0,
    ) -> None:
        # tts_ms is the wall time spent inside synthesis requests only, so this
        # stays a synthesis RTF rather than a whole-turn ratio.
        tts_rtf = round(tts_ms / tts_audio_duration_ms, 4) if tts_audio_duration_ms > 0 else None
        log.info(
            "local voice turn status=%s metrics=%s",
            status,
            {
                "vad_speech_ms": vad_speech_ms,
                "asr_ms": asr_ms,
                "llm_total_ms": llm_total_ms,
                "tts_ms": tts_ms,
                "tts_audio_duration_ms": tts_audio_duration_ms,
                "tts_gap_ms": tts_gap_ms,
                "tts_rtf": tts_rtf,
                "tts_chunks": tts_chunks,
                "filler_spoken": filler_spoken,
                "student_state": student_state,
                "hint_level": hint_level,
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


async def _finish_filler(filler: _FillerSpeech | None) -> None:
    """Let a committed notice play out; the reply's audio queues behind it."""
    if filler is not None:
        await filler.settle()


async def _drop_filler(filler: _FillerSpeech | None) -> None:
    """Abandon the notice immediately; no reply is coming on this generation."""
    if filler is not None:
        await filler.abort()
