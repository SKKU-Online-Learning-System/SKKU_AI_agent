import asyncio

import pytest

from app.core.config import Settings
from app.services.model_server.speech_client import SpeechError, SynthesisResult, TranscriptionResult
from app.services.voice.brain import VoiceContext
from app.services.voice.local_brain import VoiceBrainResult
from app.services.voice.local_cascade import LocalCascadeTransport, _tts_chunks
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
        self.synthesized_texts: list[str] = []
        self.synthesized_languages: list[str | None] = []

    async def transcribe(self, pcm: bytes, *, sample_rate: int) -> TranscriptionResult:
        self.transcribe_calls += 1
        return TranscriptionResult("가상 메모리가 뭐야?", "Korean", 1000, 100)

    async def synthesize(self, text: str, **kwargs) -> SynthesisResult:
        self.synthesize_calls += 1
        self.synthesized_texts.append(text)
        return SynthesisResult(
            b"\x01\x02" * 100,
            sample_rate=24000,
            inference_ms=25,
            audio_duration_ms=50,
        )

    async def synthesize_stream(self, text: str, **kwargs):
        self.synthesize_calls += 1
        self.synthesized_texts.append(text)
        self.synthesized_languages.append(kwargs.get("language"))
        yield b"\x01\x02" * 50, 24000
        yield b"\x01\x02" * 50, 24000


class AsrFailure(FakeSpeech):
    async def transcribe(self, pcm: bytes, *, sample_rate: int) -> TranscriptionResult:
        raise SpeechError("asr down")


class TtsFailure(FakeSpeech):
    async def synthesize(self, text: str, **kwargs) -> SynthesisResult:
        raise SpeechError("tts down")

    async def synthesize_stream(self, text: str, **kwargs):
        raise SpeechError("tts down")
        yield b"", 24000  # pragma: no cover - keeps this an async generator
        self.synthesized_languages.append(kwargs.get("language"))


class BlockingTts(FakeSpeech):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def synthesize(self, text: str, **kwargs) -> SynthesisResult:
        self.synthesize_calls += 1
        self.synthesized_texts.append(text)
        self.started.set()
        await self.release.wait()
        return SynthesisResult(b"old-audio", sample_rate=24000)

    async def synthesize_stream(self, text: str, **kwargs):
        self.synthesize_calls += 1
        self.synthesized_texts.append(text)
        self.synthesized_languages.append(kwargs.get("language"))
        self.started.set()
        await self.release.wait()
        yield b"old-audio", 24000


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        llm_provider="local_qwen",
        voice_provider="local_cascade",
        voice_llm_model="Qwen/Qwen3.5-9B",
        speech_base_url="http://speech:8010",
        **overrides,
    )


def context() -> VoiceContext:
    return VoiceContext(
        course_id="course-1",
        course_name="운영체제",
        user_id="user-1",
        memory=object(),  # type: ignore[arg-type]
    )


async def fake_brain(
    ctx,
    transcript,
    timer,
    mode,
    on_token=None,
    on_speech_delta=None,
    on_speech_rollback=None,
) -> VoiceBrainResult:
    timer.timings_ms["llm_ttft"] = 12
    timer.timings_ms["llm"] = 40
    if on_token:
        await on_token("보조 기억장치예요.")
    if on_speech_delta:
        await on_speech_delta("보조 기억장치예요.")
    return VoiceBrainResult(
        reply="보조 기억장치예요.",
        tools=["search_course_materials"],
        sources=[],
        visualizations=[],
        model_name="Qwen/Qwen3.5-9B",
    )


async def multi_sentence_brain(
    ctx,
    transcript,
    timer,
    mode,
    on_token=None,
    on_speech_delta=None,
    on_speech_rollback=None,
) -> VoiceBrainResult:
    reply = "첫 번째 문장은 이 정도로 충분히 길게 만들었습니다. 두 번째 설명입니다! 마지막 설명인가요?"
    timer.timings_ms["llm_ttft"] = 12
    timer.timings_ms["llm"] = 40
    if on_token:
        await on_token(reply)
    if on_speech_delta:
        for token in reply.split(" "):
            await on_speech_delta(token + " ")
    return VoiceBrainResult(
        reply=reply,
        tools=[],
        sources=[],
        visualizations=[],
        model_name="Qwen/Qwen3.5-9B",
    )


def test_tts_chunks_prefer_sentence_boundaries_and_cap_long_segments() -> None:
    # Every internal split is a sentence boundary and carries the sentence pause;
    # the final chunk inherits the gap the caller asked for.
    assert _tts_chunks(
        "첫 문장입니다. 둘째 문장입니다!", 80, sentence_gap_ms=180, tail_gap_ms=90
    ) == [
        ("첫 문장입니다.", 180),
        ("둘째 문장입니다!", 90),
    ]
    chunks = _tts_chunks(
        "가나다라마바사 아자차카타파하 가나다라마바사 아자차카타파하",
        20,
        sentence_gap_ms=180,
        tail_gap_ms=180,
    )
    assert chunks
    assert all(len(text) <= 20 for text, _ in chunks)
    # Word-boundary splits inside one sentence are mid-phrase: no pause until the
    # end, where the caller's boundary actually is.
    assert [gap for _, gap in chunks] == [0] * (len(chunks) - 1) + [180]


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
    await _next(events)

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
    assert speech.synthesized_languages == ["Korean"]
    await transport.close()


@pytest.mark.asyncio
async def test_multi_sentence_reply_is_synthesized_and_emitted_as_audio_chunks() -> None:
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=multi_sentence_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)

    await transport.send_text("설명해줘")
    observed = await _through_turn_done(events)
    audio_events = [event for event in observed if isinstance(event, AgentAudio)]

    # The first sentence goes out on its own so speech starts early; the rest are
    # merged into one request to avoid paying the TTS first-packet cost per
    # sentence.
    assert speech.synthesized_texts == [
        "첫 번째 문장은 이 정도로 충분히 길게 만들었습니다.",
        "두 번째 설명입니다! 마지막 설명인가요?",
    ]
    # Audio is forwarded per streamed server chunk rather than per sentence: two
    # chunks per request, plus one silent chunk re-inserting the sentence pause
    # that the seam between the two independent requests would otherwise delete.
    assert len(audio_events) == 5
    assert all(event.rate == 24000 for event in audio_events)
    gap = audio_events[2]
    assert set(gap.pcm) == {0}
    assert len(gap.pcm) == 2 * round(24000 * settings().tts_sentence_gap_ms / 1000)
    await transport.close()


async def short_opener_brain(
    ctx,
    transcript,
    timer,
    mode,
    on_token=None,
    on_speech_delta=None,
    on_speech_rollback=None,
) -> VoiceBrainResult:
    reply = "안녕하세요! 가상 메모리는 물리 메모리를 확장하는 기법이에요. 덕분에 큰 프로그램도 실행됩니다."
    timer.timings_ms["llm_ttft"] = 12
    timer.timings_ms["llm"] = 40
    if on_token:
        await on_token(reply)
    if on_speech_delta:
        for token in reply.split(" "):
            await on_speech_delta(token + " ")
    return VoiceBrainResult(
        reply=reply, tools=[], sources=[], visualizations=[], model_name="Qwen/Qwen3.5-9B"
    )


@pytest.mark.asyncio
async def test_short_opening_sentence_is_not_synthesized_on_its_own() -> None:
    """A greeting alone is too little audio to cover the request after it.

    "네!" on its own is a 2-character request worth about 200ms of playback, while
    the next packet cannot arrive for roughly 650ms, so playback stalled just
    after the greeting. tts_first_chunk_min_chars was already meant to prevent
    this but was only enforced on the clause path.
    """
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=short_opener_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("안녕")
    await _through_turn_done(events)

    first = speech.synthesized_texts[0]
    assert first.startswith("안녕하세요!")
    assert len(first) >= settings().tts_first_chunk_min_chars
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
    assert speech.synthesized_languages == ["Korean"]
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


@pytest.mark.asyncio
async def test_tool_round_preamble_is_not_spoken() -> None:
    """Text streamed during a tool round never reaches the final reply, so it
    must be rolled back instead of synthesized."""
    speech = FakeSpeech()

    async def tool_round_brain(
        ctx,
        transcript,
        timer,
        mode,
        on_token=None,
        on_speech_delta=None,
        on_speech_rollback=None,
    ) -> VoiceBrainResult:
        timer.timings_ms["llm_ttft"] = 12
        timer.timings_ms["llm"] = 40
        # Round 1: model emits preamble, then calls a tool.
        if on_speech_delta:
            await on_speech_delta("자료를 먼저 찾아볼게요. ")
        if on_speech_rollback:
            await on_speech_rollback()
        # Round 2: the real answer.
        reply = "가상 메모리는 주소 공간을 넓혀 줍니다."
        if on_token:
            await on_token(reply)
        if on_speech_delta:
            await on_speech_delta(reply)
        return VoiceBrainResult(
            reply=reply,
            tools=["search_trusted_web"],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        # Strict mode: no speech until a sentence completes, so a tool round can
        # always be rolled back before anything is spoken.
        settings=settings(tts_first_chunk_min_chars=0),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=tool_round_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")
    await _through_turn_done(events)

    assert speech.synthesized_texts == ["가상 메모리는 주소 공간을 넓혀 줍니다."]
    await transport.close()


@pytest.mark.asyncio
async def test_urls_are_stripped_from_speech_but_kept_in_transcript() -> None:
    speech = FakeSpeech()

    async def sourced_brain(
        ctx,
        transcript,
        timer,
        mode,
        on_token=None,
        on_speech_delta=None,
        on_speech_rollback=None,
    ) -> VoiceBrainResult:
        reply = "자세한 내용은 https://example.edu/os 를 참고하세요."
        timer.timings_ms["llm"] = 10
        if on_token:
            await on_token(reply)
        if on_speech_delta:
            await on_speech_delta(reply)
        return VoiceBrainResult(
            reply=reply,
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=sourced_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("참고 자료")
    observed = await _through_turn_done(events)

    assert not any("http" in text for text in speech.synthesized_texts)
    agent = [e for e in observed if isinstance(e, Transcript) and e.who == "agent"]
    assert "https://example.edu/os" in agent[0].text
    await transport.close()


@pytest.mark.asyncio
async def test_first_chunk_is_released_at_a_clause_boundary() -> None:
    """The opening chunk may be released before its sentence ends, but only at a
    clause boundary: each TTS request is generated independently, so a seam inside
    a word is audible as a click."""
    speech = FakeSpeech()

    async def slow_sentence_brain(
        ctx,
        transcript,
        timer,
        mode,
        on_token=None,
        on_speech_delta=None,
        on_speech_rollback=None,
    ) -> VoiceBrainResult:
        reply = (
            "소프트맥스 연산은 각 입력값에 지수함수를 적용한 후, "
            "모든 값의 합을 나누어 확률 분포를 만드는 과정이에요."
        )
        timer.timings_ms["llm"] = 10
        for token in reply.split(" "):
            if on_token:
                await on_token(token + " ")
            if on_speech_delta:
                await on_speech_delta(token + " ")
        return VoiceBrainResult(
            reply=reply,
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        mode="explain",
        settings=settings(tts_first_chunk_min_chars=12),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_sentence_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")
    await _through_turn_done(events)

    assert len(speech.synthesized_texts) == 2
    opening = speech.synthesized_texts[0]
    # Released early (the sentence is longer) but ending on the clause boundary,
    # not mid-word after "적용한".
    assert opening == "소프트맥스 연산은 각 입력값에 지수함수를 적용한 후,"
    # Nothing is dropped or duplicated across the seam.
    assert "".join(speech.synthesized_texts).replace(" ", "") == (
        "소프트맥스 연산은 각 입력값에 지수함수를 적용한 후, "
        "모든 값의 합을 나누어 확률 분포를 만드는 과정이에요."
    ).replace(" ", "")
    await transport.close()


async def _next(events):
    return await asyncio.wait_for(anext(events), timeout=1)


async def _through_turn_done(events) -> list[object]:
    observed: list[object] = []
    while True:
        event = await _next(events)
        observed.append(event)
        if isinstance(event, AgentTurnDone):
            return observed
