import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.voice import grok_live
from app.services.voice.transport import (
    AgentAudio,
    AgentFiller,
    AgentTextBoundary,
    AgentTextDelta,
    ToolCalled,
    Transcript,
)
from app.services.voice.visual_router import VisualDecision


class FakeWebSocket:
    def __init__(self, events: list[dict]) -> None:
        self.events = iter(json.dumps(event) for event in events)
        self.send = AsyncMock()

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return next(self.events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _settings(**overrides):
    values = {
        "grok_voice": "eve",
        "grok_voice_model": "grok-voice-latest",
        "prefix_ms": 300,
        "silence_ms": 900,
        "vad_threshold": 0.5,
        "xai_connect_attempts": 2,
        "xai_connect_retry_delay_seconds": 0,
        "xai_connect_timeout_seconds": 20,
        "xai_realtime_url": "wss://api.x.ai/v1/realtime",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_start_retries_a_timed_out_handshake(monkeypatch) -> None:
    websocket = AsyncMock()
    connect = AsyncMock(side_effect=[TimeoutError, websocket])
    monkeypatch.setattr(grok_live, "get_settings", lambda: _settings())
    monkeypatch.setattr(grok_live, "require_api_key", lambda: "secret")
    monkeypatch.setattr(grok_live.websockets, "connect", connect)

    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock())
    transport._ready.set()
    await transport.start()

    assert connect.await_count == 2
    assert connect.await_args.kwargs["open_timeout"] == 20
    websocket.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_returns_actionable_error_after_timeouts(monkeypatch) -> None:
    connect = AsyncMock(side_effect=TimeoutError)
    monkeypatch.setattr(grok_live, "get_settings", lambda: _settings())
    monkeypatch.setattr(grok_live, "require_api_key", lambda: "secret")
    monkeypatch.setattr(grok_live.websockets, "connect", connect)

    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock())

    with pytest.raises(grok_live.GrokConnectionError, match="연결 시간이 초과"):
        await transport.start()

    assert connect.await_count == 2


@pytest.mark.asyncio
async def test_duplicate_user_transcripts_are_emitted_once() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "input_audio_buffer.speech_started"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-1",
                "transcript": "트랜스포머가 뭐야?",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-1",
                "transcript": "트랜스포머가 뭐야?",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-duplicate",
                "transcript": "  트랜스포머가   뭐야?  ",
            },
        ]
    )
    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock())
    transport._ws = websocket
    transport._connected.set()

    events = [event async for event in transport.events()]
    transcripts = [event for event in events if isinstance(event, Transcript)]

    assert transcripts == [Transcript("user", "트랜스포머가 뭐야?", item_id="item-1")]


@pytest.mark.asyncio
async def test_longer_correction_replaces_the_same_user_transcript() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "input_audio_buffer.speech_started"},
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-1",
                "transcript": "트랜스포머가 왜",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-1",
                "transcript": "트랜스포머가 왜 필요한가요?",
            },
        ]
    )
    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock())
    transport._ws = websocket
    transport._connected.set()

    transcripts = [
        event
        async for event in transport.events()
        if isinstance(event, Transcript) and event.who == "user"
    ]

    assert transcripts == [
        Transcript("user", "트랜스포머가 왜", item_id="item-1"),
        Transcript(
            "user",
            "트랜스포머가 왜 필요한가요?",
            item_id="item-1",
            replace=True,
        ),
    ]


@pytest.mark.asyncio
async def test_updated_hypothesis_fills_a_truncated_completed_event() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "input_audio_buffer.speech_started"},
            {
                "type": "conversation.item.input_audio_transcription.updated",
                "item_id": "item-1",
                "transcript": "어텐션이 어떤 방식으로 동작하나요?",
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": "item-1",
                "transcript": "어텐션이 어떤 방식으로",
            },
        ]
    )
    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock())
    transport._ws = websocket
    transport._connected.set()

    transcripts = [
        event
        async for event in transport.events()
        if isinstance(event, Transcript) and event.who == "user"
    ]

    assert transcripts == [
        Transcript(
            "user",
            "어텐션이 어떤 방식으로 동작하나요?",
            item_id="item-1",
        )
    ]


@pytest.mark.asyncio
async def test_tool_preamble_is_emitted_as_filler_before_final_answer() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "response.output_audio_transcript.delta", "delta": "잠시만요. "},
            {"type": "response.output_audio_transcript.delta", "delta": "찾아볼게요."},
            {
                "type": "response.function_call_arguments.done",
                "name": "search_course_materials",
                "call_id": "call-1",
                "arguments": '{"query":"트랜스포머"}',
            },
            {"type": "response.done"},
            {"type": "response.output_audio_transcript.delta", "delta": "최종 답변이에요."},
            {"type": "response.done"},
        ]
    )
    transport = grok_live.GrokTransport(
        "Be helpful",
        [],
        AsyncMock(return_value={"found": True}),
    )
    transport._ws = websocket
    transport._connected.set()

    events = [event async for event in transport.events()]

    filler = AgentFiller("잠시만요. 찾아볼게요.")
    assert AgentTextDelta("잠시만요. ") in events
    assert AgentTextDelta("찾아볼게요.") in events
    assert filler in events
    assert events.index(filler) < next(
        index for index, event in enumerate(events) if isinstance(event, ToolCalled)
    )
    assert Transcript("agent", "최종 답변이에요.") in events


@pytest.mark.asyncio
async def test_tool_filler_gets_a_text_boundary_before_the_final_answer() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "response.output_audio_transcript.delta", "delta": "자료를 찾아볼게요."},
            {
                "type": "response.function_call_arguments.done",
                "name": "search_course_materials",
                "call_id": "call-1",
                "arguments": '{"query":"attention"}',
            },
            {"type": "response.done"},
            {"type": "response.output_audio_transcript.delta", "delta": "질문을 볼까요?"},
            {"type": "response.done"},
        ]
    )
    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock(return_value={"found": True}))
    transport._ws = websocket
    transport._connected.set()

    events = [event async for event in transport.events()]

    boundary = next(
        index for index, event in enumerate(events) if isinstance(event, AgentTextBoundary)
    )
    final = events.index(Transcript("agent", "질문을 볼까요?"))
    assert boundary < final


@pytest.mark.asyncio
async def test_barge_in_discards_cancelled_response_output() -> None:
    websocket = FakeWebSocket(
        [
            {"type": "response.created"},
            {"type": "input_audio_buffer.speech_started"},
            {"type": "response.output_audio.delta", "delta": "YWJj"},
            {"type": "response.output_audio_transcript.delta", "delta": "버려질 답변"},
            {"type": "response.done"},
        ]
    )
    transport = grok_live.GrokTransport("Be helpful", [], AsyncMock())
    transport._ws = websocket
    transport._connected.set()

    events = [event async for event in transport.events()]

    assert not any(isinstance(event, AgentAudio) for event in events)
    assert not any(isinstance(event, AgentTextDelta) for event in events)
    sent = [json.loads(call.args[0]) for call in websocket.send.await_args_list]
    assert {"type": "response.cancel"} in sent


@pytest.mark.asyncio
async def test_typed_turn_uses_the_live_conversation() -> None:
    websocket = FakeWebSocket([])
    transport = grok_live.GrokTransport(
        "Be helpful",
        [],
        AsyncMock(),
        visual_decider=AsyncMock(return_value=VisualDecision(False)),
    )
    transport._ws = websocket

    await transport.send_text("어텐션이 뭐예요?")

    sent = [json.loads(call.args[0]) for call in websocket.send.await_args_list]
    assert sent[0]["type"] == "conversation.item.create"
    assert sent[0]["item"]["content"][0]["text"] == "어텐션이 뭐예요?"
    assert sent[1] == {"type": "response.create"}
    assert transport._local_events.get_nowait() == Transcript("user", "어텐션이 뭐예요?")


@pytest.mark.asyncio
async def test_realtime_tool_has_a_hard_timeout(monkeypatch) -> None:
    async def slow_tool(_name: str, _args: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"found": True}

    websocket = FakeWebSocket(
        [
            {
                "type": "response.function_call_arguments.done",
                "name": "search_course_materials",
                "call_id": "call-1",
                "arguments": '{"query":"attention"}',
            }
        ]
    )
    monkeypatch.setattr(grok_live, "TOOL_TIMEOUT_S", 0.01)
    transport = grok_live.GrokTransport("Be helpful", [], slow_tool)
    transport._ws = websocket
    transport._connected.set()

    events = [event async for event in transport.events()]
    tool_event = next(event for event in events if isinstance(event, ToolCalled))

    assert tool_event.result == {"error": "search_course_materials timed out"}
