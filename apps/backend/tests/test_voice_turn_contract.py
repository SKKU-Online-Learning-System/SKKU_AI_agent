import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.llm_service import LLMError, ToolCallRequest, ToolTurn
from app.services.voice import brain, local_brain


VISUAL = {
    "kind": "flow",
    "title": "두 선택지",
    "caption": "두 경우를 비교해 보세요.",
    "labels": ["조건 있음", "조건 없음"],
}


def payload(**changes):
    return {
        "intent": "teach",
        "feedback": "두 경우를 비교해 봐요.",
        "question": "어느 쪽이 먼저 멈출까요?",
        "visual_action": "show",
        "visual_topic": "두 선택지 비교",
        **changes,
    }


def finish(args):
    return ToolTurn(
        "이 텍스트는 사용자에게 보내면 안 됩니다.",
        [ToolCallRequest("f", "finish_turn", args)],
        "test-model",
    )


@pytest.fixture
def runtime(monkeypatch):
    context = brain.VoiceContext("course", "수업", "learner", None)
    llm = SimpleNamespace(stream_tool_turn=AsyncMock())
    monkeypatch.setattr(local_brain, "LLMService", lambda *a, **kw: llm)
    monkeypatch.setattr(brain, "prefetch_context", AsyncMock(return_value={}))

    async def run_tool(ctx, name, args, timer):
        if name == "show_visualization":
            return brain.show_visualization(**args)
        return json.dumps({"found": True, "sources": ["https://example.org/evidence"]})

    tool = AsyncMock(side_effect=run_tool)
    monkeypatch.setattr(brain, "run_tool", tool)
    assessor = Mock()
    monkeypatch.setattr("app.services.voice.session_store.external_brain_for", lambda *a: assessor)
    return context, llm, tool, assessor


@pytest.mark.parametrize(
    "changes",
    [
        {"feedback": "_softmax가 뭐야?_", "question": "_softmax가 뭐야?_"},
        {"question": "왜일까요? 어떻게 될까요?"},
        {"feedback": "왜죠?"},
        {"question": "설명해 드릴까요?"},
        {"feedback": "가" * 121},
        {"visual_topic": ""},
        {"visual_action": "reuse", "visual_topic": ""},
        {"unexpected": "field"},
    ],
)
def test_rejects_invalid_turn_before_speech(runtime, changes):
    context, *_ = runtime
    with pytest.raises(ValueError):
        local_brain.validate_spoken_turn(payload(**changes), context, "softmax가 뭐야?")


def test_normalizes_common_9b_format_variations(runtime):
    context, *_ = runtime
    teaching = local_brain.validate_spoken_turn(
        payload(intent="social", question="새 예를 비교해 볼까요."), context, "응"
    )
    assert teaching.intent == "teach" and teaching.question.endswith("?")
    greeting = local_brain.validate_spoken_turn(
        {
            "intent": "social",
            "feedback": "안녕하세요, 무엇을 공부하고 싶으신가요?",
            "visual_action": "none",
        },
        context,
        "안녕",
    )
    assert greeting.feedback == "안녕하세요. 함께 공부해 봐요." and not greeting.question


def test_removes_repeated_previous_greeting(runtime):
    context, *_ = runtime
    previous = "안녕하세요, 인공지능 개론 수업에 오신 것을 환영합니다."
    context.history.append({"role": "assistant", "content": previous})
    turn = local_brain.validate_spoken_turn(
        payload(feedback=f"{previous} 소프트맥스는 점수를 확률로 바꿔요."),
        context,
        "softmax가 뭔지 모르겠어",
    )

    assert turn.feedback == "소프트맥스는 점수를 확률로 바꿔요."


def test_visual_plan_and_reuse(runtime):
    context, *_ = runtime
    result = local_brain.validate_spoken_turn(payload(), context, "재귀가 뭐야?")
    assert result.visual_topic == "두 선택지 비교"
    context.last_visualizations = [VISUAL]
    reused = local_brain.validate_spoken_turn(
        payload(visual_action="reuse", visual_topic=""), context, "모르겠어"
    )
    assert reused.visual_action == "reuse" and reused.visual_topic == ""


def test_plain_recovery_keeps_valid_turn_and_rejects_original_echo(runtime):
    context, *_ = runtime
    recovered = local_brain.recover_plain_turn(
        "전체를 똑같이 나누는 뜻이에요. 과자 8개를 2명이 나누면 몇 개일까요?",
        context,
        "전체를 똑같이 나누는 거야?",
    )
    assert recovered.question.endswith("?")
    normalized = local_brain.recover_plain_turn(
        "맞는 방향일까요? 새 예에서는 어떻게 될까요?", context, "응"
    )
    assert normalized.question == "새 예에서는 어떻게 될까요?"
    with pytest.raises(ValueError):
        local_brain.recover_plain_turn("_softmax가 뭐야?_", context, "softmax가 뭐야?")


@pytest.mark.asyncio
async def test_repeated_plain_echo_uses_safe_fallback_without_leaking(runtime):
    context, llm, _, _ = runtime
    llm.stream_tool_turn.return_value = ToolTurn("_softmax가 뭐야?_", [], "test")
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "softmax가 뭐야?", brain.StageTimer(), "socratic", on_speech_delta=speech
    )
    assert llm.stream_tool_turn.await_count == 2
    assert "softmax가 뭐야" not in result.reply and result.reply.count("?") == 1
    speech.assert_awaited_once_with(brain.for_speech(result.reply))


@pytest.mark.asyncio
async def test_bad_reply_is_retried_without_leaking_text_or_audio(runtime):
    context, llm, tool, assessor = runtime
    llm.stream_tool_turn.side_effect = [
        finish(
            payload(feedback="", question="softmax가 뭐야?", visual_action="none", visual_topic="")
        ),
        finish(payload()),
    ]
    tokens, speech = AsyncMock(), AsyncMock()
    result = await local_brain.think_voice(
        context,
        "softmax가 뭐야?",
        brain.StageTimer(),
        "socratic",
        on_token=tokens,
        on_speech_delta=speech,
    )
    assert llm.stream_tool_turn.await_count == 2
    tokens.assert_awaited_once_with(result.reply)
    speech.assert_awaited_once_with(brain.for_speech(result.reply))
    assert result.visual_action == "show"
    assert result.visual_topic == "두 선택지 비교"
    assert context.history[-1]["content"] == result.reply
    assert "error" in llm.stream_tool_turn.call_args.kwargs["messages"][-1]["content"]
    assert llm.stream_tool_turn.call_args.kwargs["max_tokens"] == 320
    assessor.schedule.assert_called_once()
    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_failure_stops_without_speaking_or_saving_reply(runtime):
    context, llm, _, assessor = runtime
    llm.stream_tool_turn.return_value = finish(payload(question="softmax가 뭐야?", feedback=""))
    speech = AsyncMock()
    with pytest.raises(LLMError):
        await local_brain.think_voice(
            context, "softmax가 뭐야?", brain.StageTimer(), "socratic", on_speech_delta=speech
        )
    assert llm.stream_tool_turn.await_count == 2
    speech.assert_not_awaited()
    assessor.schedule.assert_not_called()
    assert all(m["role"] == "user" for m in context.history)


@pytest.mark.asyncio
async def test_search_results_reach_final_turn(runtime):
    context, llm, tool, _ = runtime
    llm.stream_tool_turn.side_effect = [
        ToolTurn("", [ToolCallRequest("s", "search_trusted_web", {"query": "재귀"})], "test"),
        finish(payload()),
    ]
    result = await local_brain.think_voice(context, "재귀가 뭐야?", brain.StageTimer(), "socratic")
    assert result.sources == ["https://example.org/evidence"]
    assert result.tools == ["search_trusted_web"]
    assert "evidence" in llm.stream_tool_turn.call_args.kwargs["messages"][-1]["content"]
    tool.assert_awaited_once()


@pytest.mark.parametrize("question", ["안녕", "고마워", "오늘은 여기까지", "잠깐 기다려줘"])
@pytest.mark.asyncio
async def test_social_turn_needs_no_question_or_visual(runtime, question):
    context, llm, tool, _ = runtime
    llm.stream_tool_turn.return_value = finish(
        payload(
            intent="social",
            feedback="네, 알겠습니다.",
            question="",
            visual_action="none",
            visual_topic="",
        )
    )
    result = await local_brain.think_voice(context, question, brain.StageTimer(), "socratic")
    assert result.reply == "네, 알겠습니다."
    assert result.visualizations == []
    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_does_not_retry_or_speak(runtime):
    context, llm, _, assessor = runtime
    llm.stream_tool_turn.side_effect = asyncio.CancelledError
    speech = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await local_brain.think_voice(
            context, "질문", brain.StageTimer(), "socratic", on_speech_delta=speech
        )
    assert llm.stream_tool_turn.await_count == 1
    speech.assert_not_awaited()
    assessor.schedule.assert_not_called()


@pytest.mark.asyncio
async def test_unavailable_tool_is_never_executed_and_can_be_corrected(runtime):
    context, llm, tool, _ = runtime
    llm.stream_tool_turn.side_effect = [
        ToolTurn("", [ToolCallRequest("bad", "delete_file", {})], "test"),
        finish(payload()),
    ]
    result = await local_brain.think_voice(context, "재귀가 뭐야?", brain.StageTimer(), "socratic")
    assert result.visual_action == "show"
    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_truncated_generation_is_retried_without_speech(runtime):
    context, llm, _, _ = runtime
    llm.stream_tool_turn.side_effect = [LLMError("truncated"), finish(payload())]
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "재귀가 뭐야?", brain.StageTimer(), "socratic", on_speech_delta=speech
    )
    speech.assert_awaited_once_with(brain.for_speech(result.reply))
    assert llm.stream_tool_turn.await_count == 2


@pytest.mark.asyncio
async def test_visual_plan_does_not_mutate_delivered_visuals(runtime):
    context, llm, _, _ = runtime
    context.last_visualizations = [json.loads(brain.show_visualization(**VISUAL))]
    llm.stream_tool_turn.return_value = finish(payload())
    result = await local_brain.think_voice(context, "모르겠어", brain.StageTimer(), "socratic")
    assert result.visualizations == []
    assert result.visual_action == "show"
    assert result.tools == []
    assert context.last_visualizations[0]["title"] == VISUAL["title"]


@pytest.mark.asyncio
async def test_mock_provider_obeys_new_voice_contract(monkeypatch):
    from app.core.config import Settings
    from app.services.llm_service import LLMService

    settings = Settings(_env_file=None, use_mock_llm=True)
    turn = await LLMService(settings, profile="voice").stream_tool_turn(
        system="policy",
        messages=[{"role": "user", "content": "재귀가 뭐야?"}],
        tools=[{"type": "function", "function": {"name": "finish_turn"}}],
        force_tools=("finish_turn",),
    )
    context = brain.VoiceContext("c", "수업", "u", None)
    assert local_brain.validate_spoken_turn(turn.tool_calls[0].arguments, context, "재귀가 뭐야?")


def test_social_turn_can_omit_unused_question_and_visual(runtime):
    context, *_ = runtime
    turn = local_brain.validate_spoken_turn(
        {"intent": "social", "feedback": "네, 다음에 만나요.", "visual_action": "none"},
        context,
        "그만할게",
    )
    assert turn.question == "" and turn.visual_topic == ""
