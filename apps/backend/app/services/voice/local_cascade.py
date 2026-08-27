"""Interruptible local cascade voice transport.

Browser PCM is endpointed by application-side Silero VAD, then sent to the
external Speech Server for ASR. The existing COURSE AGENT brain is reused with
the Qwen voice profile and the final text is synthesized by the external TTS
server. No model weight is loaded by this transport.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from app.core.config import Settings, get_settings
from app.services.model_server.speech_client import SpeechClient, SpeechError
from app.services.safety_service import NORMAL_RESULT, SafetyGuardService, SafetyResult
from app.services.voice.brain import StageTimer, VoiceContext
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
BrainRunner = Callable[..., Awaitable[VoiceBrainResult]]
QueuedEvent = tuple[int | None, Event]


class LocalCascadeTransport(Transport):
    """ASR -> existing COURSE AGENT brain -> TTS with generation cancellation."""

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
        # Keep model-side history independent from the WebSocket event pump.
        # The pump remains the owner of the shared context and ChatLog writes.
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

        # Snapshot before emitting the transcript so route-side history updates
        # cannot race with the model-side turn.
        safety = self.safety.check_question(transcript)
        self.last_safety = safety
        await self._emit(
            Transcript("user", transcript, item_id=f"local-{generation}-user"),
            generation,
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
                )
                reply = brain_result.reply
                self.model_name = brain_result.model_name or self.model_name
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("local voice LLM turn failed")
            self._log_metrics(
                vad_speech_ms=vad_speech_ms,
                asr_ms=asr_ms,
                llm_ttft_ms=timer.timings_ms.get("llm_ttft", 0),
                llm_total_ms=timer.timings_ms.get("llm", 0),
                tts_ms=0,
                speech_end_to_first_audio_ms=0,
                total_turn_ms=round((time.perf_counter() - turn_started) * 1000),
                status="llm_failed",
            )
            await self._fail("Voice LLM 서버가 응답을 생성하지 못했습니다.", generation)
            return

        if not self._current(generation):
            return
        self.context.last_material_sources = list(self._brain_context.last_material_sources)
        self.last_web_sources = list(brain_result.sources[:3])
        await self._emit(
            Transcript("agent", reply, item_id=f"local-{generation}-agent"),
            generation,
        )
        for name in brain_result.tools:
            if name == "show_visualization":
                continue
            result = {"sources": self.last_web_sources} if name == "search_trusted_web" else None
            await self._emit(ToolCalled(name=name, result=result), generation)
        for visualization in brain_result.visualizations:
            await self._emit(
                ToolCalled(name="show_visualization", result=visualization),
                generation,
            )

        tts_started = time.perf_counter()
        try:
            synthesized = await self.speech.synthesize(
                reply,
                speaker=self.settings.tts_speaker,
                language=self.settings.tts_language,
            )
        except asyncio.CancelledError:
            raise
        except SpeechError:
            # Text has already been emitted and stays visible even when audio fails.
            tts_ms = round((time.perf_counter() - tts_started) * 1000)
            self._log_metrics(
                vad_speech_ms=vad_speech_ms,
                asr_ms=asr_ms,
                llm_ttft_ms=timer.timings_ms.get("llm_ttft", 0),
                llm_total_ms=timer.timings_ms.get("llm", 0),
                tts_ms=tts_ms,
                speech_end_to_first_audio_ms=0,
                total_turn_ms=round((time.perf_counter() - turn_started) * 1000),
                status="tts_failed",
            )
            await self._fail("음성 합성 서버가 응답 오디오를 생성하지 못했습니다.", generation)
            return
        tts_ms = round((time.perf_counter() - tts_started) * 1000)

        if not self._current(generation):
            return
        first_audio_at = time.perf_counter()
        await self._emit(AgentAudio(synthesized.pcm, rate=synthesized.sample_rate), generation)
        await self._emit(AgentTurnDone(), generation)

        self._log_metrics(
            vad_speech_ms=vad_speech_ms,
            asr_ms=asr_ms,
            llm_ttft_ms=timer.timings_ms.get("llm_ttft", 0),
            llm_total_ms=timer.timings_ms.get("llm", 0),
            tts_ms=tts_ms,
            speech_end_to_first_audio_ms=round((first_audio_at - speech_end) * 1000),
            total_turn_ms=round((time.perf_counter() - turn_started) * 1000),
            status="ok",
        )

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
    ) -> None:
        # Do not log the student's transcript by default.
        log.info(
            "local voice turn status=%s metrics=%s",
            status,
            {
                "vad_speech_ms": vad_speech_ms,
                "asr_ms": asr_ms,
                "llm_ttft_ms": llm_ttft_ms,
                "llm_total_ms": llm_total_ms,
                "tts_ms": tts_ms,
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
            # Barge-in may happen after old audio/text was queued but before the
            # event pump consumed it. Drop those stale queue entries here too.
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
