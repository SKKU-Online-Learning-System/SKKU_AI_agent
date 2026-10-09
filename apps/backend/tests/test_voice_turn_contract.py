import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import get_settings
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
        # The turn draws its own clue now, so a turn that asks to show one has to
        # carry something that will actually display.
        "visual_kind": VISUAL["kind"],
        "visual_title": VISUAL["title"],
        "visual_caption": VISUAL["caption"],
        "visual_labels": VISUAL["labels"],
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
        {"feedback": "", "question": ""},
        {"feedback": None},
        {"intent": "unknown"},
        {"visual_action": "delete"},
        {"feedback": "가" * 221},
        {"visual_topic": ""},
        {"visual_action": "reuse", "visual_topic": ""},
        {"unexpected": "field"},
    ],
)
def test_rejects_invalid_turn_before_speech(runtime, changes):
    context, *_ = runtime
    with pytest.raises(ValueError):
        local_brain.validate_spoken_turn(payload(**changes), context, "softmax가 뭐야?")


def test_model_intent_and_greeting_are_not_rewritten(runtime):
    context, *_ = runtime
    args = payload(intent="social", question="새 예를 비교해 볼까요.")
    turn = local_brain.validate_spoken_turn(args, context, "응")
    assert turn.intent == "social" and turn.question == args["question"]
    greeting = "안녕하세요, 무엇을 공부하고 싶으신가요?"
    turn = local_brain.validate_spoken_turn(
        {"intent": "social", "feedback": greeting, "visual_action": "none"}, context, "안녕"
    )
    assert turn.feedback == greeting

def test_previous_text_is_not_silently_deleted(runtime):
    context, *_ = runtime
    previous = "안녕하세요, 인공지능 개론 수업에 오신 것을 환영합니다."
    context.history.append({"role": "assistant", "content": previous})
    turn = local_brain.validate_spoken_turn(
        payload(feedback=f"{previous} 소프트맥스는 점수를 확률로 바꿔요."),
        context,
        "softmax가 뭔지 모르겠어",
    )

    assert turn.feedback == f"{previous} 소프트맥스는 점수를 확률로 바꿔요."


def test_visual_plan_and_reuse(runtime):
    context, *_ = runtime
    result = local_brain.validate_spoken_turn(payload(), context, "재귀가 뭐야?")
    assert result.visual_topic == "두 선택지 비교"
    context.last_visualizations = [VISUAL]
    reused = local_brain.validate_spoken_turn(
        payload(visual_action="reuse", visual_topic=""), context, "모르겠어"
    )
    assert reused.visual_action == "reuse" and reused.visual_topic == ""


def test_plain_recovery_preserves_words_without_semantic_filtering(runtime):
    context, *_ = runtime
    for text in [
        "전체를 똑같이 나누는 뜻이에요. 과자 8개를 2명이 나누면 몇 개일까요?",
        "맞는 방향일까요? 새 예에서는 어떻게 될까요?",
        "softmax가 뭐야?",
    ]:
        turn = local_brain.recover_plain_turn(text, context, "softmax가 뭐야?")
        assert " ".join(filter(None, [turn.feedback, turn.question])) == text

@pytest.mark.asyncio
async def test_repeated_empty_output_uses_safe_fallback_without_leaking(runtime):
    context, llm, _, _ = runtime
    llm.stream_tool_turn.return_value = ToolTurn("", [], "test")
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "softmax가 뭐야?", brain.StageTimer(), on_token=speech
    )
    assert llm.stream_tool_turn.await_count == 2
    assert "답변 생성에 문제가" in result.reply
    assert "방금 말씀" not in result.reply
    speech.assert_awaited_once_with(result.reply)


@pytest.mark.asyncio
@pytest.mark.parametrize("plain", [False, True])
async def test_invitation_and_real_question_do_not_trigger_failure(runtime, plain):
    context, llm, *_ = runtime
    context.history = [{"role": "assistant", "content": "큰 입력의 확률이 더 커요."}]
    draft = "이제 두 입력이 같은 경우를 생각해 볼까요? 입력이 모두 2라면 각각 얼마일까요?"
    llm.stream_tool_turn.return_value = (
        ToolTurn(draft, [], "test") if plain else
        finish(payload(feedback=draft, question="", visual_action="none", visual_topic=""))
    )
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "그렇겠다고", brain.StageTimer(), on_token=speech
    )
    assert result.reply == draft
    assert llm.stream_tool_turn.await_count == 1
    speech.assert_awaited_once_with(result.reply)


@pytest.mark.asyncio
async def test_bad_reply_is_retried_without_leaking_text_or_audio(runtime):
    context, llm, tool, assessor = runtime
    llm.stream_tool_turn.side_effect = [
        finish(
            payload(feedback="", question="", visual_action="none", visual_topic="")
        ),
        finish(payload()),
    ]
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context,
        "softmax가 뭐야?",
        brain.StageTimer(),
        on_token=speech,
    )
    assert llm.stream_tool_turn.await_count == 2
    speech.assert_awaited_once_with(result.reply)
    assert result.visual_action == "show"
    assert result.visual_topic == "두 선택지 비교"
    assert context.history[-1]["content"] == result.reply
    assert "error" in llm.stream_tool_turn.call_args.kwargs["messages"][-1]["content"]
    assert (
        llm.stream_tool_turn.call_args.kwargs["max_tokens"]
        == get_settings().voice_llm_max_tokens
    )
    assessor.schedule.assert_called_once()
    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_failure_stops_without_speaking_or_saving_reply(runtime):
    context, llm, _, assessor = runtime
    llm.stream_tool_turn.return_value = finish(payload(question="", feedback=""))
    speech = AsyncMock()
    with pytest.raises(LLMError):
        await local_brain.think_voice(
            context, "softmax가 뭐야?", brain.StageTimer(), on_token=speech
        )
    assert llm.stream_tool_turn.await_count == 2
    speech.assert_not_awaited()
    assessor.schedule.assert_not_called()
    assert context.history == []


SAID = "소프트맥스는 점수를 확률처럼 합이 1이 되도록 바꿔요."


def teaching(text):
    return finish(payload(feedback=text, question="", visual_action="none", visual_topic=""))


@pytest.mark.parametrize(
    ("reply", "restates"),
    [
        (SAID, True),                                   # the same turn again
        (f"{SAID} 한번 해볼까요?", True),                  # the same turn plus a tail
        ("소프트맥스는 점수를 확률처럼 합이 1이 되게 바꿔요.", True),  # reworded
        ("좋아요. 점수 2와 3이면 어느 쪽이 더 클까요?", False),      # the next step
        ("네.", False),                                  # too short to judge
    ],
)
def test_restating_the_previous_turn_is_recognised(runtime, reply, restates) -> None:
    """The evidence is re-supplied every turn, so the failure is re-delivering it."""
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": SAID}]
    assert local_brain.restates_previous_turn(context, reply) is restates


@pytest.mark.asyncio
async def test_a_repeated_answer_is_retried_before_the_student_hears_it(runtime):
    context, llm, *_ = runtime
    context.history = [
        {"role": "user", "content": "소프트맥스가 뭐야?"},
        {"role": "assistant", "content": SAID},
    ]
    llm.stream_tool_turn.side_effect = [teaching(SAID), teaching("좋아요. 2와 3 중 어느 쪽이 클까요?")]

    result = await local_brain.think_voice(context, "들어게", brain.StageTimer())

    assert result.reply == "좋아요. 2와 3 중 어느 쪽이 클까요?"
    assert llm.stream_tool_turn.await_count == 2
    assert "already said" in llm.stream_tool_turn.call_args.kwargs["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_a_second_repeat_is_still_spoken_rather_than_failing_the_turn(runtime):
    """A repeated answer is a poor turn; no answer at all is a worse one."""
    context, llm, *_ = runtime
    context.history = [
        {"role": "user", "content": "소프트맥스가 뭐야?"},
        {"role": "assistant", "content": SAID},
    ]
    llm.stream_tool_turn.return_value = teaching(SAID)

    result = await local_brain.think_voice(context, "들어게", brain.StageTimer())

    assert result.reply == SAID
    assert llm.stream_tool_turn.await_count == 2


@pytest.mark.parametrize(
    ("materials", "may_search"),
    [
        ({"found": True, "results": [{"source": "lecture.pdf p.1", "excerpt": "..."}]}, False),
        ({"found": False, "results": []}, True),
    ],
)
@pytest.mark.asyncio
async def test_web_search_is_offered_only_when_the_materials_came_up_empty(
    runtime, monkeypatch, materials, may_search
):
    """Materials first, web only as the fallback.

    The prefetch payload already said so in prose and the model searched anyway on
    most turns, spending a round on a lookup the course evidence had covered.
    """
    context, llm, *_ = runtime
    monkeypatch.setattr(
        brain, "prefetch_context", AsyncMock(return_value={"course_materials": materials})
    )
    llm.stream_tool_turn.return_value = finish(payload())

    await local_brain.think_voice(context, "소프트맥스가 뭐야?", brain.StageTimer())

    offered = [
        tool["function"]["name"] for tool in llm.stream_tool_turn.call_args.kwargs["tools"]
    ]
    assert "finish_turn" in offered
    assert ("search_trusted_web" in offered) is may_search


@pytest.mark.asyncio
async def test_search_results_reach_final_turn(runtime):
    context, llm, tool, _ = runtime
    llm.stream_tool_turn.side_effect = [
        ToolTurn("", [ToolCallRequest("s", "search_trusted_web", {"query": "재귀"})], "test"),
        finish(payload()),
    ]
    result = await local_brain.think_voice(context, "재귀가 뭐야?", brain.StageTimer())
    assert result.sources == ["https://example.org/evidence"]
    assert result.tools == ["search_trusted_web"]
    assert "evidence" in llm.stream_tool_turn.call_args.kwargs["messages"][-1]["content"]
    assert [t["function"]["name"] for t in llm.stream_tool_turn.call_args.kwargs["tools"]] == [
        "finish_turn"
    ]
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
    result = await local_brain.think_voice(context, question, brain.StageTimer())
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
            context, "질문", brain.StageTimer(), on_token=speech
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
    result = await local_brain.think_voice(context, "재귀가 뭐야?", brain.StageTimer())
    assert result.visual_action == "show"
    tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_truncated_generation_is_retried_without_speech(runtime):
    context, llm, _, _ = runtime
    llm.stream_tool_turn.side_effect = [LLMError("truncated"), finish(payload())]
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "재귀가 뭐야?", brain.StageTimer(), on_token=speech
    )
    speech.assert_awaited_once_with(result.reply)
    assert llm.stream_tool_turn.await_count == 2


@pytest.mark.asyncio
async def test_the_turn_delivers_its_own_clue_without_disturbing_earlier_ones(runtime):
    """The turn draws its clue in the same call that writes the words.

    It used to only plan one and hand the topic to a second model, so
    `visualizations` was always empty and the picture arrived after the question
    about it.
    """
    context, llm, _, _ = runtime
    earlier = json.loads(brain.show_visualization(**VISUAL))
    context.last_visualizations = [earlier]
    llm.stream_tool_turn.return_value = finish(
        payload(visual_title="새 비교", visual_caption="이번 두 경우를 비교해 보세요.")
    )

    result = await local_brain.think_voice(context, "모르겠어", brain.StageTimer())

    assert [visual["title"] for visual in result.visualizations] == ["새 비교"]
    assert result.tools == []
    # The clue already on screen is untouched, and the new one joins it.
    assert [visual["title"] for visual in context.last_visualizations] == [
        VISUAL["title"],
        "새 비교",
    ]


@pytest.mark.asyncio
async def test_reuse_shows_the_earlier_clue_again_beside_the_new_question(runtime):
    """Reuse used to emit nothing, so the brain pointed at a card several turns up
    the scroll -- or gone entirely after a reload."""
    context, llm, _, _ = runtime
    earlier = json.loads(brain.show_visualization(**VISUAL))
    context.last_visualizations = [earlier]
    llm.stream_tool_turn.return_value = finish(payload(visual_action="reuse", visual_topic=""))

    result = await local_brain.think_voice(context, "모르겠어", brain.StageTimer())

    assert result.visualizations == [earlier]
    # Shown again, not collected again.
    assert context.last_visualizations == [earlier]


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


@pytest.mark.parametrize("transcript", [
    "고마워, 그런데 왜 합이 1이야?",
    "잠깐, 회귀 문제라고 했어",
    "질문은 그만하고 한 문장으로 정리해줘",
])
def test_mixed_social_words_do_not_erase_learning_response(runtime, transcript):
    context, *_ = runtime
    turn = local_brain.validate_spoken_turn(payload(), context, transcript)
    assert turn.intent == "teach" and turn.question == payload()["question"]


def test_explanation_does_not_acquire_generic_question_or_visual(runtime):
    context, *_ = runtime
    turn = local_brain.validate_spoken_turn(
        payload(feedback="맞아요, 합이 1이라는 뜻을 짚었어요.", question="",
                visual_action="none", visual_topic=""), context, "1이요"
    )
    assert turn.question == "" and turn.visual_action == "none"
    recovered = local_brain.recover_plain_turn(turn.feedback, context, "1이요")
    assert recovered == turn


@pytest.mark.asyncio
async def test_followup_sends_actual_dialogue_and_compact_voice_policy(runtime):
    context, llm, *_ = runtime
    history = [
        {"role": "user", "content": "확률의 합을 공부하자"},
        {"role": "assistant", "content": "0.3과 0.7의 합은 얼마인가요?"},
    ]
    context.history = list(history)
    llm.stream_tool_turn.return_value = finish(payload())
    await local_brain.think_voice(context, "1이요", brain.StageTimer())
    call = llm.stream_tool_turn.call_args.kwargs
    assert call["messages"] == [*history, {"role": "user", "content": "1이요"}]
    assert "Call show_visualization" not in call["system"]
    # The compact voice policy plus the hint ladder, its per-turn stage and the
    # question the tutor left last turn, quoted so the model has something not to repeat.
    assert len(call["system"]) < 2700
    assert "# 이번 턴의 지도 단계" in call["system"]
    schema = call["tools"][-1]["function"]["parameters"]
    assert "feedback" in schema["properties"] and "question" not in schema["properties"]


def test_retrieval_follows_topic_switch_and_referential_question(runtime):
    context, *_ = runtime
    context.history = [
        {"role": "user", "content": "확률을 공부하자"},
        {"role": "assistant", "content": "확률의 합은 얼마인가요?"},
    ]
    for text in ["그거 말고 기회비용이 궁금해", "아니 회귀 문제라고 했어"]:
        assert brain.retrieval_query(context, text).endswith(text)
    assert "확률" in brain.retrieval_query(context, "아까 말한 게 뭐야?")


@pytest.mark.asyncio
async def test_valid_plain_response_is_not_discarded_or_regenerated(runtime):
    context, llm, _, assessor = runtime
    reply = "답답하셨겠어요. 첫 동전이 앞면이면 두 번째는 앞면과 뒷면 두 경우예요."
    llm.stream_tool_turn.return_value = ToolTurn(reply, [], "same-voice-model")
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "계속 모르겠어", brain.StageTimer(), on_token=speech
    )
    assert result.reply == reply and result.model_name == "same-voice-model"
    assert llm.stream_tool_turn.await_count == 1
    speech.assert_awaited_once_with(reply)
    assessor.schedule.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_plain_draft_is_repaired_with_actual_error_before_speech(runtime):
    context, llm, _, _ = runtime
    draft = "답답한 마음이 드셨겠어요. " + "동전 두 개를 함께 살펴보면 네 가지 결과가 있어요. " * 10
    corrected = "답답하셨겠어요. 첫 동전이 앞면일 때 두 번째 동전은 앞면 또는 뒷면이에요."
    llm.stream_tool_turn.side_effect = [
        ToolTurn(draft, [], "same-model"),
        finish(payload(feedback=corrected, question="", visual_action="none", visual_topic="")),
    ]
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, "계속 모르겠어", brain.StageTimer(), on_token=speech
    )
    assert result.reply == corrected
    messages = llm.stream_tool_turn.call_args.kwargs["messages"]
    assert messages[-2] == {"role": "assistant", "content": draft}
    assert "220" in messages[-1]["content"] and "failed validation" in messages[-1]["content"]
    speech.assert_awaited_once_with(corrected)
    assert [m["content"] for m in context.history] == ["계속 모르겠어", corrected]


def test_repetition_is_not_classified_by_student_keywords(runtime):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "조건을 봐요. 어느 쪽이 먼저 멈출까요?"}]
    for text in ["모르겠어", "질문을 다시 말해줘", "다시 한번 부탁"]:
        assert local_brain.validate_spoken_turn(payload(), context, text).question

@pytest.mark.parametrize("text,cue", [
    ("아니 회귀 문제라고 했어", "내가 잘못 이해했다고"),
    ("계속 모르겠어. 답답해", "한 단계를 직접"),
])
@pytest.mark.asyncio
async def test_repair_context_is_sent_without_injected_classification(runtime, text, cue):
    context, llm, *_ = runtime
    llm.stream_tool_turn.return_value = finish(payload())
    await local_brain.think_voice(context, text, brain.StageTimer())
    call = llm.stream_tool_turn.call_args.kwargs
    assert call["messages"][-1] == {"role": "user", "content": text}
    assert "이번 턴:" not in call["system"]

@pytest.mark.parametrize("text", ["그러게", "그러게요...", "글쎄요", "음...", "잘 모르겠어"])
@pytest.mark.asyncio
async def test_hesitation_is_reassured_not_marked_correct_before_audio(runtime, text):
    context, llm, *_ = runtime
    context.history = [
        {"role": "user", "content": "softmax가 뭐야?"},
        {"role": "assistant", "content": "2와 3에 softmax를 적용하면 어떻게 될까요?"},
    ]
    good = payload(
        feedback="괜찮아요. 같이 천천히 생각해 봐요. 큰 입력일수록 비중도 커져요.",
        question="2와 3 중 어느 쪽의 비중이 더 클까요?",
        visual_action="none", visual_topic="",
    )
    llm.stream_tool_turn.return_value = finish(good)
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, text, brain.StageTimer(), on_token=speech
    )
    assert llm.stream_tool_turn.await_count == 1
    assert "이번 턴:" not in llm.stream_tool_turn.call_args.kwargs["system"]
    speech.assert_awaited_once_with(result.reply)
    assert "맞아요" not in result.reply and "천천히" in result.reply


@pytest.mark.parametrize("text", ["3이 더 커요", "그러게, 3이 더 크겠네", "음, 합은 1이야"])
def test_actual_reasoning_is_not_mistaken_for_hesitation(runtime, text):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "어느 값이 더 클까요?"}]
    assert local_brain.validate_spoken_turn(payload(feedback="맞아요, 잘 짚었어요."), context, text)


def test_same_word_does_not_override_model_response(runtime):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "오늘 날씨가 좋네요."}]
    args = payload(feedback="그러게요, 산책하기 좋겠어요.", question="",
                   visual_action="none", visual_topic="", intent="social")
    assert local_brain.validate_spoken_turn(args, context, "그러게요").feedback == args["feedback"]

def test_feedback_question_can_be_moved_without_rewriting_speech(runtime):
    context, *_ = runtime
    turn = local_brain.validate_spoken_turn(
        payload(feedback="괜찮아요. 같이 천천히 생각해 봐요. 어느 입력이 더 클까요?",
                question="", visual_action="none", visual_topic=""), context, "그러게"
    )
    assert turn.feedback == "괜찮아요. 같이 천천히 생각해 봐요."
    assert turn.question == "어느 입력이 더 클까요?"


def test_existing_visual_title_does_not_discard_valid_reassurance(runtime):
    context, *_ = runtime
    context.last_visualizations = [VISUAL]
    args = payload(feedback="괜찮아요. 같이 천천히 생각해 봐요.",
                   visual_action="reuse", visual_topic=VISUAL["title"])
    turn = local_brain.validate_spoken_turn(args, context, "그러게")
    assert turn.visual_action == "reuse" and turn.visual_topic == ""
    assert turn.feedback == args["feedback"] and turn.question == args["question"]
    context.last_visualizations = []
    with pytest.raises(ValueError, match="No previous visual"):
        local_brain.validate_spoken_turn(args, context, "그러게")


@pytest.mark.parametrize("text", ["그렇겠네", "그렇겠다고", "그렇구나", "알겠어요", "응"])
@pytest.mark.asyncio
async def test_acknowledgment_after_explanation_advances_learning(runtime, text):
    context, llm, *_ = runtime
    context.history = [
        {"role": "user", "content": "소프트맥스가 뭔지 모르겠어"},
        {"role": "assistant", "content": "3이 더 큰 확률을 갖겠어요?"},
        {"role": "user", "content": "응"},
        {"role": "assistant", "content": "맞아요. 큰 입력이 더 큰 확률을 가져요."},
    ]
    llm.stream_tool_turn.return_value = finish(
        payload(feedback="이번엔 같은 크기의 입력을 볼게요.",
                question="두 입력이 모두 2라면 확률은 어떻게 나뉠까요?")
    )
    speech = AsyncMock()
    result = await local_brain.think_voice(
        context, text, brain.StageTimer(), on_token=speech
    )
    assert llm.stream_tool_turn.await_count == 1
    assert "이번 턴:" not in llm.stream_tool_turn.call_args.kwargs["system"]
    assert "두 입력이 모두 2" in result.reply
    speech.assert_awaited_once_with(result.reply)


@pytest.mark.parametrize("text", ["오늘은 여기까지", "알겠어, 그만할게", "한 문장으로 요약해줘"])
def test_learning_check_does_not_override_stop_or_summary(runtime, text):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "입력이 크면 확률도 커져요."}]
    assert local_brain.validate_spoken_turn(payload(question=""), context, text)


def test_yes_does_not_trigger_code_generated_followup(runtime):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "두 입력이 같으면 확률도 같을까요?"}]
    assert local_brain.validate_spoken_turn(payload(question=""), context, "응").question == ""

@pytest.mark.parametrize("text", ["두 값이 같으면 반반일 것 같아", "합이 1이니까 각각 0.5네"])
def test_model_decides_whether_reasoning_needs_a_followup(runtime, text):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "같은 값이면 어떻게 나뉠까요?"}]
    for question in ["", "세 입력이 같으면 어떻게 나뉠까요?"]:
        turn = local_brain.validate_spoken_turn(payload(question=question), context, text)
        assert turn.question == question

@pytest.mark.parametrize("text", ["계산은 잘 모르겠어", "예시로 설명해줘", "왜 그래?"])
def test_request_for_help_allows_explanation_without_another_quiz(runtime, text):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "같은 값이면 어떻게 나뉠까요?"}]
    assert local_brain.validate_spoken_turn(payload(question=""), context, text)


def test_teachback_and_acknowledgment_are_passed_to_model_not_graded(runtime):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "배운 내용을 한 문장으로 정리해 볼까요?"}]
    for text in ["지수값을 그 합으로 나눠서 합이 1이 돼요", "그렇겠네"]:
        assert local_brain.validate_spoken_turn(payload(question=""), context, text).question == ""

def test_speech_budget_applies_to_whole_reply_not_provider_field_split(runtime):
    context, *_ = runtime
    text = "괜찮아요. " + "작은 예시부터 함께 살펴보면 돼요. " * 6
    assert 120 < len(text) < 220
    assert local_brain.validate_spoken_turn(
        payload(feedback=text, question="", visual_action="none", visual_topic=""),
        context, "잘 모르겠어",
    ).feedback == text.strip()
    with pytest.raises(ValueError, match="entire spoken reply"):
        local_brain.validate_spoken_turn(payload(feedback="가" * 215), context, "잘 모르겠어")


def test_single_plain_question_is_valid_without_fabricating_feedback(runtime):
    context, *_ = runtime
    turn = local_brain.recover_plain_turn("두 입력이 같으면 확률도 같을까요?", context, "그렇겠네")
    assert turn.feedback == "두 입력이 같으면 확률도 같을까요?"
    assert turn.question == ""


def test_validator_does_not_rewrite_model_question(runtime):
    context, *_ = runtime
    args = payload(feedback="입력이 클수록 확률이 높아요.", question="입력이 클수록 확률이 높아요?")
    assert local_brain.validate_spoken_turn(args, context, "그렇겠네").question == args["question"]

@pytest.mark.parametrize("text", ["그렇겠네", "그렇겠다고", "알겠어"])
def test_validator_does_not_grade_passive_agreement(runtime, text):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "큰 입력의 확률이 더 커요."}]
    assert local_brain.validate_spoken_turn(payload(feedback="맞아요."), context, text).feedback == "맞아요."

def test_semantic_quality_is_evaluated_outside_transport_validation(runtime):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": "큰 입력은 큰 확률을 가져요."}]
    # This is a pedagogy failure for live evaluation, not a malformed transport payload.
    assert local_brain.validate_spoken_turn(
        payload(feedback="완전히 이해하셨네요."), context, "그렇겠네"
    ).feedback == "완전히 이해하셨네요."


# --------------------------------------------------------------------------
# The hint ladder: Socratic teaching is enforced per turn, not just requested.

LECTURE = (
    "스케일드 닷 프로덕트 어텐션은 점곱 점수의 분산을 줄여 소프트맥스가 너무 날카로워지는 것을 막는 "
    "방법이에요. 차원 수가 커질수록 점곱 점수의 분산도 커지는데, 이를 루트 d로 나누어 안정화해요."
)
HINT = "이름부터 볼게요. 두 벡터의 내적은 차원이 커지면 값이 어떻게 될 것 같나요?"
ASKED = "스케일드닷 프로덕터 텐션이 뭔지 모르겠어."


def classified(text, state):
    return finish(
        payload(feedback=text, question="", visual_action="none", visual_topic="", student_state=state)
    )


@pytest.mark.parametrize(
    ("level", "state", "expected"),
    [
        (0, "new_question", 0),
        (0, "stuck", 1),
        (1, "stuck", 2),
        (2, "wrong", 3),
        (3, "stuck", 3),
        (2, "partial", 2),
        (2, "correct", 0),
        (0, "wants_answer", 3),
        (1, "social", 1),
    ],
)
def test_hint_ladder_climbs_one_rung_per_stuck_turn(level, state, expected):
    assert brain.next_hint_level(level, state) == expected


def test_stage_section_names_the_rung_for_the_next_stuck_turn():
    context = brain.VoiceContext("course", "수업", "learner", None)
    context.hint_level = 1
    stage = brain.socratic_stage(context)
    assert "막힌 횟수 1번" in stage
    assert brain.HINT_LADDER[2] in stage
    assert brain.HINT_LADDER[brain.REVEAL_LEVEL] in stage


def test_the_prompt_carries_the_stage_and_reset_clears_the_ladder():
    context = brain.VoiceContext("course", "수업", "learner", None)
    context.hint_level = 2
    assert "막힌 횟수 2번" in brain.answer_instructions(context, {})
    context.reset()
    assert context.hint_level == 0


@pytest.mark.parametrize(
    ("reply", "fragment"),
    [
        (LECTURE, "질문 하나로"),
        (f"{LECTURE} 그러면 왜 나눌까요?", "너무 길어요"),
    ],
)
def test_a_lecture_where_a_hint_is_due_is_a_violation(runtime, reply, fragment):
    context, *_ = runtime
    turn = local_brain.validate_spoken_turn(
        payload(feedback=reply, question="", visual_action="none", visual_topic="",
                student_state="new_question"),
        context, ASKED,
    )
    assert fragment in local_brain.socratic_violation(turn, context)


@pytest.mark.parametrize(
    ("reply", "state", "level"),
    [
        (HINT, "new_question", 0),
        ("괜찮아요. 1이 백 개면 곱해서 더한 값은요? 차원이 커지면 내적은 커질까요, 작아질까요?", "stuck", 0),
        (LECTURE, "wants_answer", 0),          # the student asked to be told
        (LECTURE, "stuck", 2),                 # third stuck turn: the reveal rung
        ("네, 오늘은 여기까지 할게요.", "social", 0),
    ],
)
def test_hints_reveals_and_social_turns_keep_the_ladder(runtime, reply, state, level):
    context, *_ = runtime
    context.hint_level = level
    turn = local_brain.validate_spoken_turn(
        payload(feedback=reply, question="", visual_action="none", visual_topic="",
                student_state=state, intent="social" if state == "social" else "teach"),
        context, "모르겠어",
    )
    assert local_brain.socratic_violation(turn, context) is None


def test_hint_before_question_measures_only_the_preamble():
    assert local_brain.hint_before_question(HINT) == "이름부터 볼게요."
    assert local_brain.hint_before_question("어느 쪽이 클까요?") == ""
    assert local_brain.hint_before_question(LECTURE) == LECTURE


@pytest.mark.asyncio
async def test_a_lecture_is_rewritten_once_before_the_student_hears_it(runtime):
    context, llm, *_ = runtime
    llm.stream_tool_turn.side_effect = [
        classified(LECTURE, "new_question"),
        classified(HINT, "new_question"),
    ]
    speech = AsyncMock()

    result = await local_brain.think_voice(context, ASKED, brain.StageTimer(), on_token=speech)

    assert result.reply == HINT
    speech.assert_awaited_once_with(HINT)
    rewrite = llm.stream_tool_turn.call_args.kwargs
    assert "질문 하나로" in rewrite["messages"][-1]["content"]
    assert "두 문장만" in rewrite["system"]
    assert [m["content"] for m in context.history] == [ASKED, HINT]


@pytest.mark.asyncio
async def test_a_second_lecture_is_spoken_rather_than_failing_the_turn(runtime):
    context, llm, *_ = runtime
    llm.stream_tool_turn.return_value = classified(LECTURE, "new_question")

    result = await local_brain.think_voice(context, ASKED, brain.StageTimer())

    assert result.reply == LECTURE
    assert llm.stream_tool_turn.await_count == 2


@pytest.mark.asyncio
async def test_the_ladder_follows_the_student_through_the_conversation(runtime):
    context, llm, *_ = runtime
    steps = [
        ("new_question", HINT, 0),
        ("stuck", "괜찮아요. 1이 백 개면요? 내적은 커질까요, 작아질까요?", 1),
        ("stuck", "커지죠. 그 큰 값을 소프트맥스에 넣으면 무엇으로 나눠야 할까요?", 2),
        ("stuck", "점수를 차원의 제곱근으로 나눠요. 왜 나누는지 한 문장으로 말해 볼까요?", 3),
        ("correct", "맞아요. 그러면 차원이 4일 때는 얼마로 나눌까요?", 0),
    ]
    for state, reply, level in steps:
        llm.stream_tool_turn.return_value = classified(reply, state)
        result = await local_brain.think_voice(context, "...", brain.StageTimer())
        assert result.reply == reply
        assert context.hint_level == level
    assert llm.stream_tool_turn.await_count == len(steps)


@pytest.mark.asyncio
async def test_finish_turn_schema_makes_the_model_classify_before_it_speaks(runtime):
    context, llm, *_ = runtime
    llm.stream_tool_turn.return_value = classified(HINT, "new_question")
    await local_brain.think_voice(context, ASKED, brain.StageTimer())
    schema = llm.stream_tool_turn.call_args.kwargs["tools"][-1]["function"]["parameters"]
    fields = list(schema["properties"])
    assert "student_state" in schema["required"]
    assert fields.index("student_state") < fields.index("feedback")


WITHHELD = "점수를 차원의 제곱근으로 나누어 분산을 안정화한다."


@pytest.mark.parametrize(
    ("reply", "leaks"),
    [
        (HINT, False),
        ("그래서 점수를 차원의 제곱근으로 나누어 크기를 조절해요. 왜 그럴까요?", True),
        ("차원이 커지면 값이 커지죠. 그러면 무엇으로 나눠야 할까요?", False),
    ],
)
def test_the_spoken_words_are_checked_against_the_answer_the_model_withheld(runtime, reply, leaks):
    context, *_ = runtime
    turn = local_brain.validate_spoken_turn(
        payload(feedback=reply, question="", visual_action="none", visual_topic="",
                student_state="stuck", withheld_answer=WITHHELD),
        context, "모르겠어",
    )
    violation = local_brain.socratic_violation(turn, context)
    assert (violation is not None and "withheld_answer" in violation) is leaks


def test_the_withheld_answer_may_be_spoken_at_the_reveal_rung(runtime):
    context, *_ = runtime
    context.hint_level = 2
    turn = local_brain.validate_spoken_turn(
        payload(feedback=f"{WITHHELD} 왜 나누는지 한 문장으로 말해 볼까요?", question="",
                visual_action="none", visual_topic="", student_state="stuck",
                withheld_answer=WITHHELD),
        context, "모르겠어",
    )
    assert local_brain.socratic_violation(turn, context) is None


# ---------------------------------------------------------------------------
# The same question again after "몰라"
# ---------------------------------------------------------------------------

PROBE = "이름부터 볼게요. 두 벡터의 내적은 차원이 커지면 값이 어떻게 될 것 같나요?"


def test_the_stage_quotes_the_question_the_student_was_left_with():
    context = brain.VoiceContext("course", "수업", "learner", None)
    assert "직전 내 질문" not in brain.socratic_stage(context)
    context.history = [{"role": "assistant", "content": PROBE}]
    assert brain.last_assistant_question(context) == PROBE.split(" ", 2)[2]
    assert "두 벡터의 내적은 차원이 커지면 값이 어떻게 될 것 같나요?" in brain.socratic_stage(context)
    context.history = [{"role": "assistant", "content": "네, 오늘은 여기까지 할게요."}]
    assert "직전 내 질문" not in brain.socratic_stage(context)


@pytest.mark.parametrize(
    ("transcript", "with_history", "state"),
    [
        ("몰라", True, "stuck"),
        ("음 모르겠어요", True, "stuck"),
        ("힌트 좀 주세요", True, "stuck"),
        ("몰라", False, None),                      # nothing yet to be stuck on
        ("안녕하세요", False, "social"),
        ("소프트맥스 연산이 뭔지 모르겠어", True, None),  # names a concept: the model decides
        ("내적이요", True, None),
    ],
)
def test_the_words_alone_decide_stuck_and_social(transcript, with_history, state):
    context = brain.VoiceContext("course", "수업", "learner", None)
    if with_history:
        context.history = [{"role": "assistant", "content": PROBE}]
    assert brain.rule_based_student_state(context, transcript) == state


def test_a_bare_not_knowing_is_stuck_whatever_the_model_called_it(runtime):
    """new_question after "몰라" reset the ladder and repeated the probe."""
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": PROBE}]
    turn = local_brain.validate_spoken_turn(
        payload(feedback="괜찮아요.", question="2차원과 100차원 중 어디서 값이 더 클까요?",
                visual_action="none", visual_topic="", student_state="new_question"),
        context, "몰라",
    )
    assert turn.student_state == "stuck"
    # A concept named is a new question, and the model's word stands.
    turn = local_brain.validate_spoken_turn(
        payload(feedback="괜찮아요.", question="점수가 뭘까요?", visual_action="none",
                visual_topic="", student_state="new_question"),
        context, "소프트맥스가 뭔지 모르겠어",
    )
    assert turn.student_state == "new_question"


@pytest.mark.parametrize(
    ("reply", "repeats"),
    [
        (PROBE, True),
        ("괜찮아요. 두 벡터의 내적은 차원이 커지면 값이 어떻게 될 것 같나요?", True),   # new hint, same question
        ("괜찬아요. 두 벡터의 내적은 차원이 커지면 값이 어떻게 될까요?", True),         # reworded
        ("괜찮아요. 2차원과 100차원 중 어느 쪽 내적이 더 클까요?", False),             # a smaller question
        ("네.", False),
    ],
)
def test_the_question_sentence_is_compared_on_its_own(runtime, reply, repeats):
    context, *_ = runtime
    context.history = [{"role": "assistant", "content": PROBE}]
    assert local_brain.repeats_previous_question(context, reply) is repeats
    assert local_brain.restates_previous_turn(context, "괜찬아요. " + PROBE.split(" ", 2)[2]) in (True, False)


@pytest.mark.asyncio
async def test_the_same_question_after_stuck_is_rewritten_and_climbs_the_ladder(runtime):
    context, llm, *_ = runtime
    context.history = [
        {"role": "user", "content": "스케일드 닷 프로덕트 어텐션이 뭔지 모르겠어."},
        {"role": "assistant", "content": PROBE},
    ]
    llm.stream_tool_turn.side_effect = [
        finish(payload(feedback="괜찮아요.", question=PROBE.split(" ", 2)[2],
                       visual_action="none", visual_topic="", student_state="new_question")),
        finish(payload(feedback="괜찮아요.", question="2차원과 100차원 중 어느 쪽 내적이 더 클까요?",
                       visual_action="none", visual_topic="", student_state="new_question")),
    ]

    result = await local_brain.think_voice(context, "몰라", brain.StageTimer())

    assert result.reply == "괜찮아요. 2차원과 100차원 중 어느 쪽 내적이 더 클까요?"
    assert llm.stream_tool_turn.await_count == 2
    rewrite = llm.stream_tool_turn.call_args.kwargs
    assert "already asked" in rewrite["messages"][-1]["content"]
    assert "두 벡터의 내적은" in rewrite["messages"][-1]["content"]
    # The server read "몰라" as stuck, so the ladder climbed instead of resetting.
    assert result.student_state == "stuck"
    assert context.hint_level == 1
