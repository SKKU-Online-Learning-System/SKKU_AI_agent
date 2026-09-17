"""Headlines for the model's streamed reasoning: paced, ordered, never gating the turn."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.services.llm_service import LLMError, LLMService, ToolTurn
from app.services.voice import brain
from app.services.voice.thoughts import FLUSH_MIN_CHARS, ThoughtSummarizer

SETTINGS = Settings(
    _env_file=None,
    use_mock_llm=True,
    thought_summary_min_chars=100,
    thought_summary_interval_seconds=4.0,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class SlowSummaryLLM:
    """Answers each chunk with a headline after a short await, recording calls."""

    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.calls: list[dict] = []
        self.fail = fail
        self.delay = delay

    async def summarize_reasoning(self, *, previous, chunk):
        self.calls.append({"previous": list(previous), "chunk": chunk})
        await asyncio.sleep(self.delay)
        if self.fail:
            raise LLMError("Voice LLM Model Server를 사용할 수 없습니다.")
        return f'"{len(self.calls)}번째: 접근을 정한다."\n두 번째 줄은 버린다'


def collector():
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    return events, on_event


@pytest.mark.asyncio
async def test_headlines_are_paced_by_characters_and_seconds_and_arrive_in_order() -> None:
    events, on_event = collector()
    clock = FakeClock()
    llm = SlowSummaryLLM()
    summarizer = ThoughtSummarizer(
        llm=llm, settings=SETTINGS, on_event=on_event, key="llm-1", clock=clock
    )

    summarizer.feed("가" * 60)  # under the character floor: nothing yet
    await asyncio.sleep(0)
    assert llm.calls == []

    summarizer.feed("나" * 60)  # over it: the first headline starts
    await asyncio.sleep(0.01)
    assert len(llm.calls) == 1 and llm.calls[0]["chunk"] == "가" * 60 + "나" * 60

    summarizer.feed("다" * 200)  # enough text, but too soon after the last one
    await asyncio.sleep(0.01)
    assert len(llm.calls) == 1

    clock.now += 5
    summarizer.feed("라")  # the interval has passed: the pending text goes out
    await asyncio.sleep(0.01)
    assert len(llm.calls) == 2 and llm.calls[1]["chunk"] == "다" * 200 + "라"
    assert llm.calls[1]["previous"] == ["1번째: 접근을 정한다"]

    await summarizer.close()
    assert [e["text"] for e in events] == ["1번째: 접근을 정한다", "2번째: 접근을 정한다"]
    assert all(e["type"] == "thought" and e["key"] == "llm-1" for e in events)


@pytest.mark.asyncio
async def test_flush_summarizes_a_worthwhile_tail_and_close_cancels_what_is_running() -> None:
    events, on_event = collector()
    llm = SlowSummaryLLM(delay=0.2)
    summarizer = ThoughtSummarizer(llm=llm, settings=SETTINGS, on_event=on_event, key="llm-1")

    summarizer.feed("짧은 꼬리")
    summarizer.flush()  # under FLUSH_MIN_CHARS: not worth a call
    assert llm.calls == []

    summarizer.feed("마" * FLUSH_MIN_CHARS)
    summarizer.flush()
    await asyncio.sleep(0.01)
    assert len(llm.calls) == 1
    # The round ends before the headline is back: the turn does not wait for it.
    await summarizer.close()
    assert events == []
    summarizer.feed("바" * 500)  # closed: ignored
    await asyncio.sleep(0.01)
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_a_failing_summary_model_is_skipped_quietly() -> None:
    events, on_event = collector()
    summarizer = ThoughtSummarizer(
        llm=SlowSummaryLLM(fail=True), settings=SETTINGS, on_event=on_event, key="llm-1"
    )
    summarizer.feed("사" * 200)
    await asyncio.sleep(0.01)
    await summarizer.close()
    assert events == []


@pytest.mark.asyncio
async def test_summaries_are_off_without_a_listener_or_when_disabled() -> None:
    llm = SlowSummaryLLM()
    silent = ThoughtSummarizer(llm=llm, settings=SETTINGS, on_event=None, key="llm-1")
    silent.feed("아" * 500)
    off = ThoughtSummarizer(
        llm=llm,
        settings=Settings(_env_file=None, use_mock_llm=True, text_thought_summaries=False),
        on_event=AsyncMock(),
        key="llm-1",
    )
    off.feed("자" * 500)
    await asyncio.sleep(0.01)
    assert llm.calls == []


@pytest.mark.asyncio
async def test_the_mock_summary_is_korean_and_the_prompt_asks_for_a_headline() -> None:
    llm = LLMService(Settings(_env_file=None, use_mock_llm=True), profile="voice")
    assert "생각을 정리하는 중" in await llm.summarize_reasoning(previous=[], chunk="reasoning")


@pytest.mark.asyncio
async def test_think_emits_thought_headlines_under_the_round(monkeypatch) -> None:
    """The reasoning of a round yields raw `thinking` deltas and, beside them,
    paced `thought` headlines keyed to the same step; the answer is unaffected."""

    class ReasoningLLM:
        def __init__(self) -> None:
            self.profile = None

        async def stream_tool_turn(self, **kwargs):
            for _ in range(5):
                await kwargs["on_reasoning"]("학생은 소프트맥스의 정의를 묻고 있다. " * 8)
                await asyncio.sleep(0)
            await kwargs["on_token"]("이름부터 볼게요. ")
            await asyncio.sleep(0.02)
            return ToolTurn("이름부터 볼게요. 맥스는 무엇을 고를까요?", [], "test")

    class Summaries:
        provider = "local_qwen"
        calls = 0

        async def summarize_reasoning(self, *, previous, chunk):
            Summaries.calls += 1
            return "이름을 뜯어보며 접근 방식을 정한다"

    def make_llm(_settings, profile="text"):
        return Summaries() if profile == "voice" else ReasoningLLM()

    memory = AsyncMock()
    memory.all_memories.return_value = []
    context = brain.VoiceContext("course-1", "인공지능개론", "student-1", memory)
    events, on_event = collector()
    monkeypatch.setattr(brain, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(brain, "LLMService", make_llm)
    monkeypatch.setattr(
        brain, "search_course_materials", lambda *_: (json.dumps({"found": False}), [])
    )

    reply, *_ = await brain.think(
        context, "소프트맥스가 뭐야?", brain.StageTimer(), on_token=AsyncMock(), on_event=on_event
    )

    assert reply.startswith("이름부터 볼게요.")
    thoughts = [e for e in events if e["type"] == "thought"]
    assert thoughts and all(e["key"] == "llm-1" for e in thoughts)
    assert thoughts[0]["text"] == "이름을 뜯어보며 접근 방식을 정한다"
    # Repeats are not shown twice in a row.
    assert len(thoughts) == 1
    assert Summaries.calls >= 1
    # The raw deltas still stream, keyed the same way.
    assert all(e["key"] == "llm-1" for e in events if e["type"] == "thinking")
