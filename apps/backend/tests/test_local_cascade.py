import asyncio

import pytest

from app.core.config import Settings
from app.services.model_server.speech_client import SpeechError, SynthesisResult, TranscriptionResult
from app.services.voice.brain import VoiceContext
from app.services.voice.local_brain import VoiceBrainResult
from app.services.voice.local_cascade import LocalCascadeTransport
from app.services.voice.transport import (
    AgentAudio,
    AgentTextDelta,
    AgentTurnDone,
    Failed,
    Transcript,
    UserStartedSpeaking,
    UserStoppedSpeaking,
)


class FakeDetector:
    def __init__(self) -> None:
        self.speaking = False
        self.calls = 0

    def feed(self, frame: bytes) -> bytes | None:
        self.calls += 1
        if self.calls == 1:
            self.speaking = True
            return None
        self.speaking = False
        return b"\x00\x00" * 16000


class FakeSpeech:
    def __init__(self) -> None:
        self.transcribe_calls = 0
        self.synthesize_calls = 0

    async def transcribe(self, pcm: bytes, *, sample_rate: int) -> TranscriptionResult:
        self.transcribe_calls += 1
        return TranscriptionResult("가상 메모리가 뭐야?", "Korean", 1000, 100)

    async def synthesize(self, text: str, **kwargs) -> SynthesisResult:
        self.synthesize_calls += 1
        return SynthesisResult(b"\x01\x02" * 100, sample_rate=24000)


class AsrFailure(FakeSpeech):
    async def transcribe(self, pcm: bytes, *, sample_rate: int) -> TranscriptionResult:
        raise SpeechError("asr down")


class TtsFailure(FakeSpeech):
    async def synthesize(self, text: str, **kwargs) -> SynthesisResult:
        raise SpeechError("tts down")


class BlockingTts(FakeSpeech):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def synthesize(self, text: str, **kwargs) -> SynthesisResult:
        self.synthesize_calls += 1
        self.started.set()
        await self.release.wait()
        return SynthesisResult(b"old-audio", sample_rate=24000)


def settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="local_qwen",
        voice_provider="local_cascade",
        voice_llm_model="Qwen/Qwen3.5-9B",
        speech_base_url="http://speech:8010",
    )


def context() -> VoiceContext:
    return VoiceContext(
        course_id="course-1",
        course_name="운영체제",
        user_id="user-1",
        memory=object(),  # type: ignore[arg-type]
    )


async def fake_brain(ctx, transcript, timer, mode, on_token=None) -> VoiceBrainResult:
    timer.timings_ms["llm_ttft"] = 12
    timer.timings_ms["llm"] = 40
    if on_token:
        await on_token("보조 기억장치예요.")
    return VoiceBrainResult(
        reply="보조 기억장치예요.",
        tools=["search_course_materials"],
        sources=[],
        visualizations=[],
        model_name="Qwen/Qwen3.5-9B",
    )


@pytest.mark.asyncio
async def test_audio_turn_runs_vad_asr_voice_brain_tts() -> None:
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=fake_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)  # SessionReady

    await transport.send_audio(b"frame-1")
    assert isinstance(await _next(events), UserStartedSpeaking)
    await transport.send_audio(b"frame-2")

    observed = await _through_turn_done(events)
    assert isinstance(observed[0], UserStoppedSpeaking)
    assert any(isinstance(event, Transcript) and event.who == "user" for event in observed)
    assert any(isinstance(event, AgentTextDelta) for event in observed)
    assert any(isinstance(event, Transcript) and event.who == "agent" for event in observed)
    assert any(isinstance(event, AgentAudio) and event.rate == 24000 for event in observed)
    assert speech.transcribe_calls == 1
    assert speech.synthesize_calls == 1
    await transport.close()


@pytest.mark.asyncio
async def test_send_text_skips_asr_and_uses_same_tts_pipeline() -> None:
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        mode="socratic",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=fake_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)

    await transport.send_text("가상 메모리가 뭐야?")
    observed = await _through_turn_done(events)

    assert isinstance(observed[0], UserStoppedSpeaking)
    assert speech.transcribe_calls == 0
    assert speech.synthesize_calls == 1
    assert any(isinstance(event, AgentAudio) for event in observed)
    await transport.close()


@pytest.mark.asyncio
async def test_asr_failure_stops_before_llm_and_tts() -> None:
    called = False

    async def brain(*args, **kwargs):
        nonlocal called
        called = True
        return await fake_brain(*args, **kwargs)

    speech = AsrFailure()
    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_audio(b"frame-1")
    await _next(events)
    await transport.send_audio(b"frame-2")
    assert isinstance(await _next(events), UserStoppedSpeaking)
    assert isinstance(await _next(events), Failed)
    assert called is False
    assert speech.synthesize_calls == 0
    await transport.close()


@pytest.mark.asyncio
async def test_tts_failure_keeps_agent_text_visible() -> None:
    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=TtsFailure(),  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=fake_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")

    observed = []
    while True:
        event = await _next(events)
        observed.append(event)
        if isinstance(event, Failed):
            break

    assert any(isinstance(event, Transcript) and event.who == "agent" for event in observed)
    assert not any(isinstance(event, AgentAudio) for event in observed)
    await transport.close()


@pytest.mark.asyncio
async def test_llm_failure_does_not_call_tts() -> None:
    speech = FakeSpeech()

    async def broken_brain(*args, **kwargs):
        raise RuntimeError("voice llm down")

    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=broken_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("테스트")

    observed = []
    while True:
        event = await _next(events)
        observed.append(event)
        if isinstance(event, Failed):
            break
    assert speech.synthesize_calls == 0
    assert not any(isinstance(event, AgentAudio) for event in observed)
    await transport.close()


@pytest.mark.asyncio
async def test_barge_in_cancels_old_tts_and_no_old_audio_is_emitted_after_start() -> None:
    speech = BlockingTts()
    detector = FakeDetector()
    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=detector,  # type: ignore[arg-type]
        brain_runner=fake_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)

    await transport.send_text("첫 질문")
    await asyncio.wait_for(speech.started.wait(), timeout=1)
    await transport.send_audio(b"interrupt")

    seen_start = False
    audio_after_start = False
    while not seen_start:
        event = await _next(events)
        if isinstance(event, UserStartedSpeaking):
            seen_start = True
    await transport.close()
    async for event in events:
        if isinstance(event, AgentAudio):
            audio_after_start = True

    assert seen_start is True
    assert audio_after_start is False


async def _next(events):
    return await asyncio.wait_for(anext(events), timeout=1)


async def _through_turn_done(events) -> list[object]:
    observed: list[object] = []
    while True:
        event = await _next(events)
        observed.append(event)
        if isinstance(event, AgentTurnDone):
            return observed
