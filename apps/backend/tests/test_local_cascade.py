import asyncio

import pytest

from app.core.config import Settings
from app.services.safety_service import SafetyResult
from app.services.model_server.speech_client import (
    SpeechError,
    SynthesisResult,
    TranscriptionResult,
)
from app.services.voice.brain import VoiceContext, for_speech
from app.services.voice.filler import ALL_FILLERS, is_progress_notice
from app.services.voice.local_brain import VoiceBrainResult
from app.services.voice.local_cascade import LocalCascadeTransport, _tts_chunks
from app.services.voice.transport import (
    AgentAudio,
    AgentFiller,
    AgentTextDelta,
    AgentTurnDone,
    ToolCalled,
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


async def fake_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
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


async def multi_sentence_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
    reply = (
        "첫 번째 문장은 이 정도로 충분히 길게 만들었습니다. 두 번째 설명입니다! 마지막 설명인가요?"
    )
    timer.timings_ms["llm"] = 40
    if on_token:
        await on_token(reply)
    return VoiceBrainResult(
        reply=reply,
        tools=[],
        sources=[],
        visualizations=[],
        model_name="Qwen/Qwen3.5-9B",
    )


def test_tts_chunks_prefer_sentence_boundaries_and_cap_long_segments() -> None:
    # Every internal split is a sentence boundary and carries the sentence pause;
    # the last chunk ends the turn, so it needs no trailing silence.
    assert _tts_chunks(
        "첫 문장입니다. 둘째 문장입니다!",
        first_max_chars=80,
        max_chars=80,
        sentence_gap_ms=180,
    ) == [
        ("첫 문장입니다.", 180),
        ("둘째 문장입니다!", 0),
    ]
    chunks = _tts_chunks(
        "가나다라마바사 아자차카타파하 가나다라마바사 아자차카타파하",
        first_max_chars=20,
        max_chars=20,
        sentence_gap_ms=180,
    )
    assert chunks
    assert all(len(text) <= 20 for text, _ in chunks)
    # Word-boundary splits inside one sentence are mid-phrase: pausing there
    # sounds like a stall, and the final chunk ends the turn.
    assert [gap for _, gap in chunks] == [0] * len(chunks)


def test_tts_chunks_cut_a_long_opening_only_at_a_clause_boundary() -> None:
    chunks = _tts_chunks(
        "짧게 말하면, 가상 메모리는 물리 메모리를 넘어서는 주소 공간을 제공합니다.",
        first_max_chars=16,
        max_chars=80,
        clause_gap_ms=90,
    )
    # The opening is cut after "짧게 말하면," and the seam keeps the clause pause.
    assert chunks[0] == ("짧게 말하면,", 90)
    assert "".join(text for text, _ in chunks[1:]).startswith("가상 메모리는")


@pytest.mark.asyncio
async def test_audio_turn_runs_vad_asr_voice_brain_tts() -> None:
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
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


async def short_opener_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
    reply = "안녕하세요! 가상 메모리는 물리 메모리를 확장하는 기법이에요. 덕분에 큰 프로그램도 실행됩니다."
    timer.timings_ms["llm"] = 40
    if on_token:
        await on_token(reply)
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
    """A typed turn on a live session is a student who cannot use the microphone.

    It skips ASR and nothing else: same brain, same validated reply, same speech,
    so they hear the answer even though they could not speak the question.
    """
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
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
async def test_only_the_validated_reply_is_synthesized() -> None:
    """The brain releases one finished utterance, so nothing else can be spoken.

    Preamble text a tool round produced never reaches ``reply``; it used to have
    to be rolled back out of a half-filled TTS queue, and now simply never
    reaches the transport.
    """
    speech = FakeSpeech()

    async def tool_round_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        timer.timings_ms["llm"] = 40
        reply = "가상 메모리는 주소 공간을 넓혀 줍니다."
        if on_token:
            await on_token(reply)
        return VoiceBrainResult(
            reply=reply,
            tools=["search_trusted_web"],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
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

    async def sourced_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        reply = "자세한 내용은 https://example.edu/os 를 참고하세요."
        timer.timings_ms["llm"] = 10
        if on_token:
            await on_token(reply)
        return VoiceBrainResult(
            reply=reply,
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
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
async def test_long_opening_sentence_is_cut_at_a_clause_boundary() -> None:
    """The first request is the whole first-audio latency, so a long opening
    sentence is cut short -- but only at a clause boundary: each TTS request is
    generated independently, so a seam inside a word is audible as a click."""
    speech = FakeSpeech()

    async def long_sentence_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        reply = (
            "소프트맥스 연산은 각 입력값에 지수함수를 적용한 후, "
            "모든 값의 합을 나누어 확률 분포를 만드는 과정이에요."
        )
        timer.timings_ms["llm"] = 10
        if on_token:
            await on_token(reply)
        return VoiceBrainResult(
            reply=reply,
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(tts_first_chunk_max_chars=30),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=long_sentence_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("소프트맥스")
    await _through_turn_done(events)

    assert len(speech.synthesized_texts) == 2
    # Cut at the clause boundary that fits, not mid-word after "적용한".
    assert speech.synthesized_texts[0] == "소프트맥스 연산은 각 입력값에 지수함수를 적용한 후,"
    # Nothing is dropped or duplicated across the seam.
    assert "".join(speech.synthesized_texts).replace(" ", "") == (
        "소프트맥스 연산은 각 입력값에 지수함수를 적용한 후, "
        "모든 값의 합을 나누어 확률 분포를 만드는 과정이에요."
    ).replace(" ", "")
    await transport.close()


@pytest.mark.asyncio
async def test_barge_in_leaves_no_unanswered_question_in_the_history() -> None:
    """Interrupting is ordinary in speech, so it must not corrupt the context.

    The question used to be appended before the model ran, so every cancelled
    turn left a user message with no answer beside it. A handful of interruptions
    then filled the bounded history with orphans and pushed the real dialogue out.
    """
    ctx = context()

    async def never_finishes(inner_ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(5)
        raise AssertionError("the turn should have been cancelled")

    transport = LocalCascadeTransport(
        context=ctx,
        settings=settings(),
        speech_client=FakeSpeech(),  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=never_finishes,
    )
    await transport.start()
    for question in ["첫 질문", "둘째 질문", "셋째 질문"]:
        await transport.send_text(question)
        await asyncio.sleep(0)

    assert ctx.history == []
    await transport.close()


@pytest.mark.asyncio
async def test_reported_tts_time_excludes_the_llm_wait() -> None:
    """tts_ms is a synthesis measurement, so the logged RTF stays comparable.

    It used to run from before the brain started, which folded the whole LLM
    latency into the ratio and inflated it several times over.
    """
    speech = FakeSpeech()

    async def slow_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(0.2)
        timer.timings_ms["llm"] = 200
        return VoiceBrainResult(
            reply="짧은 답이에요.",
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_brain,
    )
    recorded: list[dict] = []
    transport._log_metrics = lambda **kw: recorded.append(kw)  # type: ignore[method-assign]
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("질문")
    await _through_turn_done(events)

    metrics = recorded[-1]
    assert metrics["status"] == "ok"
    assert metrics["llm_total_ms"] >= 200
    assert metrics["tts_ms"] < 100
    assert metrics["total_turn_ms"] >= metrics["llm_total_ms"] + metrics["tts_ms"]
    await transport.close()


class BlockingSafety:
    """SAFE guard that refuses, so the turn answers without consulting a model."""

    def check_question(self, text: str) -> SafetyResult:
        return SafetyResult(
            blocked=True,
            category="exam_answer",
            safe_answer="시험 답안은 드릴 수 없어요. 어떤 부분이 막히는지 말해 주세요.",
        )


class SlowFirstTts(FakeSpeech):
    """TTS whose first packet is slow, so the filler can lose the race on purpose."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    async def synthesize_stream(self, text: str, **kwargs):
        self.synthesize_calls += 1
        self.synthesized_texts.append(text)
        self.synthesized_languages.append(kwargs.get("language"))
        await asyncio.sleep(self.delay)
        yield b"\x01\x02" * 50, 24000


@pytest.mark.asyncio
async def test_progress_notice_is_spoken_while_the_model_is_still_working() -> None:
    """A validated-then-released reply means a slow turn is otherwise pure silence."""
    speech = FakeSpeech()

    async def slow_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(0.1)
        timer.timings_ms["llm"] = 100
        return VoiceBrainResult(
            reply="주소 공간을 넓혀 줍니다.",
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")
    observed = await _through_turn_done(events)

    notice = [event for event in observed if isinstance(event, AgentFiller)]
    assert len(notice) == 1
    assert is_progress_notice(notice[0].text)
    assert "가상 메모리" in notice[0].text, "the notice echoes what the student asked about"
    # Shown as a progress notice the answer replaces, not as a turn of its own.
    assert notice[0].transient is True
    # Spoken, and entirely before the reply: audio plays in arrival order.
    assert speech.synthesized_texts[0] == for_speech(notice[0].text)
    assert "주소 공간" in " ".join(speech.synthesized_texts[1:])
    await transport.close()


@pytest.mark.asyncio
async def test_notice_audio_is_marked_so_latency_still_measures_the_answer() -> None:
    """The badge is the wait for an answer, not for the notice that covers it.

    The notice only plays on turns slow enough to need it, so timing the first
    audio would report ~the TTS latency on exactly the turns that were slowest.
    """
    speech = FakeSpeech()

    async def slow_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(0.1)
        return VoiceBrainResult("주소 공간을 넓혀 줍니다.", [], [], [], "Qwen/Qwen3.5-9B")

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")
    observed = await _through_turn_done(events)

    audio = [event for event in observed if isinstance(event, AgentAudio)]
    assert audio[0].filler is True, "the notice plays first and must be marked"
    assert any(not event.filler for event in audio), "the answer must still be spoken"
    # Every unmarked chunk belongs to the reply, which is emitted after the notice.
    assert [event.filler for event in audio] == sorted(
        (event.filler for event in audio), reverse=True
    )
    await transport.close()


@pytest.mark.asyncio
async def test_progress_notice_is_dropped_unheard_when_the_reply_wins() -> None:
    """A spoken notice delays the answer behind it, so a fast turn must not pay it."""
    speech = SlowFirstTts(0.2)

    async def instant_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        timer.timings_ms["llm"] = 1
        return VoiceBrainResult(
            reply="주소 공간을 넓혀 줍니다.",
            tools=[],
            sources=[],
            visualizations=[],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=instant_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")
    observed = await _through_turn_done(events)

    # The notice is still shown instantly; only its audio is abandoned.
    notices = [event.text for event in observed if isinstance(event, AgentFiller)]
    assert notices
    transcripts = "".join(event.text for event in observed if isinstance(event, Transcript))
    assert not any(notice in transcripts for notice in notices)
    audio = b"".join(event.pcm for event in observed if isinstance(event, AgentAudio))
    assert audio == b"\x01\x02" * 50
    await transport.close()


@pytest.mark.asyncio
async def test_typing_mid_utterance_does_not_leave_two_turns_on_one_generation() -> None:
    """A finished utterance supersedes a turn typed while it was still being said.

    Speech onset claims a generation, so the endpoint normally has nothing to
    cancel. A typed turn submitted in between claims one *after* the onset, and
    the endpoint would then answer into that same generation: two turns alive at
    once, their audio interleaved into one playback stream and both logged.
    """

    class ScriptedDetector:
        """Frame 1 is a speech onset; frame 2 is the endpoint with an utterance."""

        def __init__(self) -> None:
            self.speaking = False
            self.calls = 0

        def feed(self, frame: bytes) -> bytes | None:
            self.calls += 1
            if self.calls == 1:
                self.speaking = True
                return None
            self.speaking = False
            return b"\x00\x00" * 1600

    class TaggedSpeech(FakeSpeech):
        async def transcribe(self, pcm: bytes, *, sample_rate: int) -> TranscriptionResult:
            self.transcribe_calls += 1
            return TranscriptionResult("말한 질문", "Korean", 1000, 100)

        async def synthesize_stream(self, text: str, **kwargs):
            self.synthesize_calls += 1
            self.synthesized_texts.append(text)
            await asyncio.sleep(0.02)
            yield (b"\xaa\xaa" if "말한" in text else b"\xbb\xbb") * 100, 24000

    async def echo_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(0.05)
        return VoiceBrainResult(f"{transcript} 에 대한 답", [], [], [], "Qwen/Qwen3.5-9B")

    speech = TaggedSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        # The progress notice has its own audio; this is about turn collision.
        settings=settings(voice_spoken_filler=False),
        speech_client=speech,  # type: ignore[arg-type]
        detector=ScriptedDetector(),  # type: ignore[arg-type]
        brain_runner=echo_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)

    await transport.send_audio(b"frame-onset")
    await transport.send_text("타이핑한 질문")
    typed_turn = transport._active_task
    await transport.send_audio(b"frame-endpoint")

    assert typed_turn is not transport._active_task
    assert typed_turn is not None and typed_turn.cancelled()

    observed = await _through_turn_done(events)
    spoken = [event for event in observed if isinstance(event, AgentAudio)]
    assert spoken, "the superseding utterance must still be answered"
    # Only the newer intent reaches the single playback stream.
    assert all(event.pcm[:2] == b"\xaa\xaa" for event in spoken)
    await transport.close()


@pytest.mark.asyncio
async def test_barge_in_is_not_delayed_by_a_notice_already_speaking() -> None:
    """Interrupting must feel immediate even mid-notice.

    A committed notice is played to its end on the normal path, but barge-in
    awaits the cancelled turn: waiting there for the rest of a synthesis request
    would make the agent feel unresponsive exactly when the student cuts in.
    """
    started = asyncio.Event()

    class NeverEndingTts(FakeSpeech):
        async def synthesize_stream(self, text: str, **kwargs):
            self.synthesize_calls += 1
            self.synthesized_texts.append(text)
            yield b"\x01\x02" * 50, 24000
            started.set()
            await asyncio.sleep(30)  # a request that never completes
            yield b"\x01\x02" * 50, 24000

    async def slow_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(30)
        raise AssertionError("the turn should have been cancelled")

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=NeverEndingTts(),  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_brain,
    )
    await transport.start()
    await transport.send_text("가상 메모리")
    await asyncio.wait_for(started.wait(), timeout=2)

    # The notice has committed and is mid-request; interrupting must not wait it out.
    await asyncio.wait_for(transport.send_audio(b"interrupt"), timeout=2)
    await transport.close()


@pytest.mark.asyncio
async def test_blocked_answer_shows_no_progress_notice() -> None:
    """A safety answer is already written, so there is nothing to wait for."""
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=fake_brain,
        safety_service=BlockingSafety(),  # type: ignore[arg-type]
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("시험 답 알려줘")
    observed = await _through_turn_done(events)

    assert not any(isinstance(event, AgentFiller) for event in observed)
    assert not any(notice in " ".join(speech.synthesized_texts) for notice in ALL_FILLERS)
    await transport.close()


@pytest.mark.asyncio
async def test_a_greeting_gets_no_progress_notice() -> None:
    """A turn that is not waiting for an answer is answered without a "잠시만요"."""
    speech = FakeSpeech()

    async def slow_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(0.1)
        return VoiceBrainResult(
            "안녕하세요! 오늘은 뭘 공부해 볼까요?", [], [], [], "Qwen/Qwen3.5-9B"
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("안녕하세요")
    observed = await _through_turn_done(events)

    assert not any(isinstance(event, AgentFiller) for event in observed)
    assert not any(event.filler for event in observed if isinstance(event, AgentAudio))
    assert "안녕하세요" in " ".join(speech.synthesized_texts), "the reply itself is still spoken"
    await transport.close()


@pytest.mark.asyncio
async def test_spoken_progress_notice_can_be_turned_off() -> None:
    speech = FakeSpeech()

    async def slow_brain(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        await asyncio.sleep(0.1)
        return VoiceBrainResult("답이에요.", [], [], [], "Qwen/Qwen3.5-9B")

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(voice_spoken_filler=False),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=slow_brain,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("가상 메모리")
    observed = await _through_turn_done(events)

    # Still shown on screen, never synthesized.
    notices = [event.text for event in observed if isinstance(event, AgentFiller)]
    assert notices
    assert not any(notice in " ".join(speech.synthesized_texts) for notice in notices)
    await transport.close()


@pytest.mark.parametrize("input_kind", ["text", "audio"])
@pytest.mark.asyncio
async def test_real_voice_brain_never_synthesizes_rejected_reply(monkeypatch, input_kind):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.services.llm_service import ToolCallRequest, ToolTurn
    from app.services.voice import brain, local_brain

    good = {
        "intent": "teach",
        "feedback": "한정된 공간을 나눠 쓰는 상황이에요.",
        "question": "공간이 부족하면 어떻게 나눠 쓸까요?",
        "visual_action": "none",
    }
    bad = {**good, "feedback": "", "question": ""}
    llm = SimpleNamespace(
        stream_tool_turn=AsyncMock(
            side_effect=[
                ToolTurn("bad preamble", [ToolCallRequest("bad", "finish_turn", bad)], "test"),
                ToolTurn("", [ToolCallRequest("good", "finish_turn", good)], "test"),
            ]
        )
    )
    monkeypatch.setattr(local_brain, "LLMService", lambda *a, **kw: llm)
    monkeypatch.setattr(brain, "prefetch_context", AsyncMock(return_value={}))
    monkeypatch.setattr(
        "app.services.voice.session_store.external_brain_for",
        lambda *a: SimpleNamespace(schedule=Mock()),
    )
    speech = FakeSpeech()
    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(),
        speech_client=speech,
        detector=FakeDetector(),
        brain_runner=local_brain.think_voice,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    try:
        if input_kind == "text":
            await transport.send_text("가상 메모리가 뭐야?")
        else:
            await transport.send_audio(b"frame-1")
            await transport.send_audio(b"frame-2")
        observed = await _through_turn_done(events)
        answers = [e.text for e in observed if isinstance(e, Transcript) and e.who == "agent"]
        assert answers == [good["feedback"] + " " + good["question"]]
        spoken = " ".join(speech.synthesized_texts)
        assert "가상 메모리가 뭐야?" not in spoken
        assert "bad preamble" not in spoken
        assert good["question"] in spoken
        assert llm.stream_tool_turn.await_count == 2
        assert speech.transcribe_calls == (input_kind == "audio")
    finally:
        await transport.close()


async def _next(events):
    return await asyncio.wait_for(anext(events), timeout=1)


@pytest.mark.asyncio
async def test_the_clue_is_shown_before_the_reply_is_spoken() -> None:
    """The student sees the clue, then hears the words about it.

    The clue used to be drawn by a second model running alongside the speech, so
    it landed after the question that referred to it and the policy had to forbid
    pointing at it. The brain draws it in the same call now, so it is on screen
    before any audio.
    """
    speech = FakeSpeech()
    visual = {
        "kind": "flow",
        "title": "두 경우",
        "caption": "비교해 보세요.",
        "labels": ["조건 있음", "조건 없음"],
    }

    async def brain_with_clue(ctx, transcript, timer, on_token=None) -> VoiceBrainResult:
        timer.timings_ms["llm"] = 40
        return VoiceBrainResult(
            reply="두 경우를 비교해 봐요. 어느 쪽이 먼저 멈출까요?",
            tools=[],
            sources=[],
            visualizations=[visual],
            model_name="Qwen/Qwen3.5-9B",
        )

    transport = LocalCascadeTransport(
        context=context(),
        settings=settings(voice_spoken_filler=False),
        speech_client=speech,  # type: ignore[arg-type]
        detector=FakeDetector(),  # type: ignore[arg-type]
        brain_runner=brain_with_clue,
    )
    await transport.start()
    events = transport.events()
    await _next(events)
    await transport.send_text("소프트맥스가 뭐야?")
    observed = await _through_turn_done(events)

    kinds = [type(event).__name__ for event in observed]
    drawn = next(
        index
        for index, event in enumerate(observed)
        if isinstance(event, ToolCalled) and event.name == "show_visualization"
    )
    assert observed[drawn].result == visual
    # Before the agent's words, and before a single sample of audio.
    assert drawn < kinds.index("Transcript", kinds.index("Transcript") + 1)
    assert drawn < kinds.index("AgentAudio")
    await transport.close()


@pytest.mark.asyncio
async def test_no_second_model_is_consulted_for_the_clue() -> None:
    """The brain's own clue is used as-is; nothing may veto or redraw it."""
    import app.services.voice.local_cascade as cascade

    assert not hasattr(cascade, "decide_visualization")
    assert not hasattr(cascade.LocalCascadeTransport, "_render_visual")


async def _through_turn_done(events) -> list[object]:
    observed: list[object] = []
    while True:
        event = await _next(events)
        observed.append(event)
        if isinstance(event, AgentTurnDone):
            return observed
