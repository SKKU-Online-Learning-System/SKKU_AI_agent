"""Voice-profile wrapper around the existing COURSE AGENT brain.

The core RAG, memory, tool execution, prompts and policies stay in brain.py.
The voice loop requests a bounded finish_turn and validates its speech and visual
before releasing either. Search and visualization still use the shared brain tools.

Nothing is released until the whole turn validates, so the transport receives a
finished reply rather than a stream. The conversation is only extended once that
reply exists: an abandoned turn (barge-in, model failure) must not leave the
student's question in the history with no answer beside it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.llm_service import LLMError, LLMService, ToolCallRequest
from app.services.voice import brain

log = logging.getLogger("voice.local-brain")
MAX_FINISH_RETRIES = 1
# A turn that is valid speech but poor teaching (a repeat, a lecture where a hint
# was due) gets its own single retry. It must not spend the hard-failure budget:
# a picky rewrite that then hits a truncation would otherwise hand the student an
# error message instead of, at worst, the lecture.
MAX_SOFT_RETRIES = 1


class SoftViolation(ValueError):
    """The draft would speak fine, but it teaches badly; ask for one rewrite."""
class SpokenTurn(BaseModel):
    """One bounded utterance and its visual clue, validated before any speech."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intent: Literal["teach", "social"] = Field(
        description="social for greeting, thanks, goodbye or pause; otherwise teach"
    )
    # Decided before the words are written: the schema order is the generation
    # order, and the rung of the hint ladder depends on this classification.
    student_state: Literal[
        "new_question", "stuck", "wrong", "partial", "correct", "wants_answer", "social"
    ] = Field(
        default="partial",
        description="What the student's last turn was: new_question asks about a concept "
        "(including 'X가 뭔지 모르겠어' naming X); stuck could not answer my question, "
        "including a bare '몰라'/'모르겠어요' with no concept named; wrong answered "
        "incorrectly; partial answered partly; correct answered; wants_answer explicitly "
        "asks to stop questioning and be told; social for greetings and closings.",
    )
    # Written before the utterance so the model names the answer it is holding
    # back, and the validator can check the words it speaks against it.
    withheld_answer: str = Field(
        default="",
        max_length=120,
        description="One Korean sentence: the answer or definition the student is working "
        "toward, which this turn must NOT say (unless 3단계). Never spoken.",
    )
    feedback: str = Field(
        max_length=220,
        description="The entire Korean utterance. Below 3단계 exactly two sentences: one hint "
        "sentence (no definition of the concept, at most 90 characters), then one question "
        "the student can answer, ending with '?'. At 3단계: the answer in two sentences, then "
        "one request to restate it.",
    )
    question: str = Field(
        default="",
        max_length=100,
        description="At most one concrete reasoning question; empty when no question is useful",
    )
    visual_action: Literal["show", "reuse", "none"] = Field(
        description="show for a new comparison, process, structure or formula; reuse an existing "
        "matching clue; none for purely verbal feedback or social turns"
    )
    visual_topic: str = Field(
        default="",
        max_length=80,
        description="Short topic for a new visual; empty for reuse or none",
    )
    visual_kind: Literal["formula", "flow", "none"] = Field(
        default="none",
        description="formula for an equation or relationship, flow for a process or structure",
    )
    visual_title: str = Field(default="", max_length=40, description="Korean title for the clue")
    visual_caption: str = Field(
        default="",
        max_length=80,
        description="Korean one-line clue, never the answer itself",
    )
    visual_latex: str = Field(default="", description="LaTeX body; required when kind is formula")
    visual_labels: list[str] = Field(
        default_factory=list,
        description="Two or more Korean step labels; required when kind is flow",
    )


def drawn_clue(turn: SpokenTurn) -> dict | None:
    """Render the clue this turn asked for, raising if it would not display.

    The brain draws its own clue rather than handing a topic to a second model.
    That second model never disagreed with it (0 of 6 measured) while costing a
    whole extra voice-profile generation, and -- the part that mattered -- it
    produced the picture *after* the words were composed, so the reply could
    never refer to what the student was about to see.
    """
    if turn.visual_action != "show":
        return None
    return json.loads(
        brain.show_visualization(
            kind=turn.visual_kind,
            title=turn.visual_title,
            caption=turn.visual_caption,
            latex=turn.visual_latex,
            labels=turn.visual_labels,
        )
    )


def validate_spoken_turn(args: dict, context: brain.VoiceContext, transcript: str) -> SpokenTurn:
    """Validate the transport contract, not the student's meaning or teaching quality.

    The one exception is a student_state the words decide on their own: a bare
    "몰라" after a tutor question is stuck whatever the model called it, because
    calling it new_question resets the ladder and repeats the probe.
    """
    normalized = dict(args)
    if normalized.get("visual_action") in {"reuse", "none"}:
        # A turn not drawing anything carries no drawing, whatever it filled in.
        normalized.update(
            visual_topic="", visual_kind="none", visual_title="",
            visual_caption="", visual_latex="", visual_labels=[],
        )
    # Accept the legacy split fields without changing the spoken words.
    feedback = str(normalized.get("feedback", "")).strip()
    if not normalized.get("question") and feedback.endswith(("?", "？")):
        parts = re.split(r"(?<=[.!。！])\s+", feedback)
        if len(parts) > 1 and len(parts[-1]) <= 100:
            normalized.update(feedback=" ".join(parts[:-1]), question=parts[-1])
    turn = SpokenTurn.model_validate(normalized)
    reply = f"{turn.feedback} {turn.question}".strip()
    if not reply:
        raise ValueError("Provide a nonempty spoken reply.")
    if len(reply) > 220:
        raise ValueError("Keep the entire spoken reply within 220 characters.")
    if (turn.visual_action == "show") != bool(turn.visual_topic):
        raise ValueError("Provide visual_topic only when requesting a new visual.")
    if turn.visual_action == "reuse" and not context.last_visualizations:
        raise ValueError("No previous visual is available to reuse.")
    if turn.intent == "social" and turn.student_state != "social":
        turn = turn.model_copy(update={"student_state": "social"})
    plain = brain.rule_based_student_state(context, transcript)
    if plain == "stuck" and turn.student_state != "stuck":
        log.info("student_state %s overridden to stuck for %r", turn.student_state, transcript)
        turn = turn.model_copy(update={"student_state": "stuck"})
    return turn


_compact = brain._compact


def hint_before_question(reply: str) -> str:
    """The part of the reply spoken before its final question sentence."""
    sentences = re.split(r"(?<=[.!?。！？])\s+", reply.strip())
    last_question = max(
        (index for index, sentence in enumerate(sentences) if "?" in sentence or "？" in sentence),
        default=None,
    )
    if last_question is None:
        return reply.strip()
    return " ".join(sentences[:last_question]).strip()


# A shared run of this many compacted characters between the spoken words and
# the answer the model said it was withholding means the answer was spoken.
LEAK_RUN = 8


def leaked_answer(reply: str, withheld: str) -> str:
    """The longest stretch of the withheld answer that the reply says verbatim."""
    said, held = _compact(reply), _compact(withheld)
    if len(held) < LEAK_RUN or len(said) < LEAK_RUN:
        return ""
    match = SequenceMatcher(None, said, held, autojunk=False).find_longest_match(
        0, len(said), 0, len(held)
    )
    return held[match.b : match.b + match.size] if match.size >= LEAK_RUN else ""


def socratic_violation(turn: SpokenTurn, context: brain.VoiceContext) -> str | None:
    """Why this teach turn breaks the hint ladder, or None when it keeps it.

    Below the reveal rung a turn must leave the student a question and must
    spend no more than the rung's hint budget before it. A turn that ends
    without a question has lectured instead of taught; a turn that explains the
    concept for 150 characters and then asks "so why is that?" has done the
    same with a quiz stapled on. Whether the short hint that remains gives the
    answer away is still the model's job.
    """
    if turn.intent == "social" or turn.student_state == "social":
        return None
    level = brain.next_hint_level(context.hint_level, turn.student_state)
    if level >= brain.REVEAL_LEVEL:
        return None
    reply = f"{turn.feedback} {turn.question}".strip()
    if not (reply.count("?") + reply.count("？")):
        return (
            f"{brain.HINT_LADDER[level]} 정답이나 정의를 설명하지 말고, 학생이 답할 수 있는 "
            "질문 하나로 끝나도록 finish_turn을 다시 작성하세요."
        )
    # More than one question mark is left alone: an invitation ("같이 볼까요?")
    # followed by the real question is natural speech, not a second quiz.
    budget = brain.HINT_BUDGET[level]
    spent = len(hint_before_question(reply))
    if spent > budget:
        return (
            f"질문 앞의 설명이 {spent}자로 너무 길어요. 이 턴은 {brain.HINT_LADDER[level]} "
            f"설명은 {budget}자 이내 한 문장으로 줄이고, 정의나 정답은 빼고, 질문 하나로 끝내세요."
        )
    leaked = leaked_answer(reply, turn.withheld_answer)
    if leaked:
        return (
            f"'{leaked}'는 withheld_answer의 내용이라 이 단계에서는 말하면 안 돼요. "
            f"{brain.HINT_LADDER[level]} 답을 빼고 힌트와 질문만 다시 쓰세요."
        )
    return None


# Shared with the text path, which repeats itself for the same reason.
REPEAT_RATIO = brain.REPEAT_RATIO
restates_previous_turn = brain.restates_previous_turn
repeats_previous_question = brain.repeats_previous_question


def recover_plain_turn(text: str, context: brain.VoiceContext, transcript: str) -> SpokenTurn:
    """Preserve a plain completion; no lexical inference of student intent."""
    return validate_spoken_turn(
        {"intent": "teach", "feedback": text.strip(), "visual_action": "none"},
        context,
        transcript,
    )


@dataclass(frozen=True)
class VoiceBrainResult:
    reply: str
    tools: list[str]
    sources: list[str]
    visualizations: list[dict]
    model_name: str
    visual_action: Literal["show", "reuse", "none"] = "none"
    visual_topic: str = ""
    # How the ladder read this turn, for the per-turn metrics line.
    student_state: str = ""
    hint_level: int = 0


async def think_voice(
    context: brain.VoiceContext,
    transcript: str,
    timer: brain.StageTimer,
    on_token: Callable[[str], Awaitable[None]] | None = None,
) -> VoiceBrainResult:
    """Run the existing brain policy with the Qwen voice profile."""
    question = {"role": "user", "content": transcript}
    context.last_material_sources = []
    settings = get_settings()
    llm = LLMService(settings, profile="voice")
    tool_messages: list[dict] = []
    tools_used: list[str] = []
    external_sources: list[str] = []
    visualizations: list[dict] = []

    prefetched = await brain.prefetch_context(context, transcript, timer)
    system = brain.answer_instructions(context, prefetched, voice=True) + (
        "\nSubmit the final utterance through finish_turn, never plain text. "
        "Fill the visual fields when a clue helps the next step; the student sees it "
        "before you speak, so you may point at it. "
        "feedback contains the ENTIRE utterance, at most 220 characters and one question. "
        "Use only supported numbers. "
        "Never say your previous turn again; answer the student and move on. "
        "If you searched, use its result before finish_turn."
    )
    # Materials first, web only when they came up empty. This was already the
    # policy in the prefetch payload's own instruction, but as prose the model
    # ignored it on most turns and spent a round on a search it did not need.
    evidence_found = bool(prefetched.get("course_materials", {}).get("found"))
    tools = [
        tool
        for tool in brain.TOOLS
        if tool["function"]["name"] == "search_trusted_web" and not evidence_found
    ]
    spoken_schema = SpokenTurn.model_json_schema()
    # One speech field for the model; accept split legacy replies internally as before.
    spoken_schema["properties"].pop("question")
    spoken_schema["required"] = sorted(
        {*spoken_schema.get("required", []), "student_state", "withheld_answer"}
    )
    tools.append(
        {
            "type": "function",
            "function": {
                "name": "finish_turn",
                "description": "Submit the Korean Socratic utterance and visual clue.",
                "parameters": spoken_schema,
            },
        }
    )
    if getattr(settings, "voice_trace_content", False):
        log.info(
            "voice llm input transcript=%.4000s system=%.4000s history=%.8000r",
            transcript,
            system,
            context.history,
        )

    failures = 0
    soft_failures = 0
    for _ in range(brain.MAX_TOOL_ROUNDS):
        started_at = time.perf_counter()
        try:
            turn = await llm.stream_tool_turn(
                system=system,
                messages=[*brain._conversation([*context.history, question]), *tool_messages],
                # ponytail: one web lookup per turn; expand if evidence-gap evaluations need it.
                tools=tools[-1:] if failures or soft_failures or tools_used else tools,
                force_tools=("finish_turn",),
                max_tokens=settings.voice_llm_max_tokens,
            )
        except LLMError:
            if failures >= MAX_FINISH_RETRIES:
                raise
            failures += 1
            system += "\nPrevious generation failed. Submit a shorter complete finish_turn."
            continue
        finally:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            timer.timings_ms["llm"] = timer.timings_ms.get("llm", 0) + elapsed_ms
        if getattr(settings, "voice_trace_content", False):
            log.info(
                "voice llm output model=%s text=%.8000s tool_calls=%.4000r",
                turn.model_name,
                turn.text,
                turn.tool_calls,
            )

        if not turn.tool_calls:
            try:
                recovered = recover_plain_turn(turn.text, context, transcript)
            except (ValueError, TypeError) as exc:
                if failures < MAX_FINISH_RETRIES:
                    failures += 1
                    # Repair the actual rejected draft instead of regenerating blindly.
                    tool_messages.extend([
                        {"role": "assistant", "content": turn.text},
                        {
                            "role": "user",
                            "content": (
                                f"Your draft failed validation: {exc}\n"
                                "Rewrite it through finish_turn: entire reply <=220 characters "
                                "with at most one question. Preserve "
                                "the useful explanation; do not ask the student to repeat."
                            ),
                        },
                    ])
                    continue
                else:
                    log.warning("using safe voice fallback after invalid plain turn: %s", exc)
                    recovered = validate_spoken_turn(
                        {
                            "intent": "social",
                            "feedback": "죄송해요. 답변 생성에 문제가 생겼어요. 잠시 후 다시 시도해 주세요.",
                            "visual_action": "none",
                        },
                        context,
                        transcript,
                    )
            turn = type(turn)(
                "",
                [ToolCallRequest("recovered", "finish_turn", recovered.model_dump())],
                turn.model_name,
            )

        tool_messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in turn.tool_calls
                ],
            }
        )

        for call in turn.tool_calls:
            if call.name == "finish_turn":
                try:
                    if len(turn.tool_calls) != 1:
                        raise ValueError("Read the search results, then submit finish_turn alone.")
                    spoken = validate_spoken_turn(call.arguments, context, transcript)
                    reply = " ".join(
                        filter(None, [spoken.feedback.strip(), spoken.question.strip()])
                    )
                    # Only while a soft retry is left and no hard retry has been
                    # spent: a repeated answer or a lecture is a poor turn, but a
                    # third generation, or failing the turn outright, would leave
                    # the student waiting or with nothing at all, which is worse.
                    can_rewrite = failures == 0 and soft_failures < MAX_SOFT_RETRIES
                    # The question is checked first: it is the more specific
                    # complaint, and a repeated probe is what keeps the student
                    # on the same rung.
                    if can_rewrite and repeats_previous_question(context, reply):
                        raise SoftViolation(
                            f"'{brain.last_assistant_question(context)}' is the question you "
                            "already asked and the student could not answer. Ask a smaller "
                            "sub-question or come at it from another angle instead."
                        )
                    if can_rewrite and restates_previous_turn(context, reply):
                        raise SoftViolation(
                            "You already said this. Respond to what the student just "
                            "said and take the next step instead of explaining the "
                            "same thing again."
                        )
                    # A plain completion recovered above never classified the
                    # student, so the ladder cannot judge it; only a turn the model
                    # submitted itself is held to the rung it chose.
                    violation = (
                        socratic_violation(spoken, context) if call.id != "recovered" else None
                    )
                    if can_rewrite and violation:
                        raise SoftViolation(violation)
                    # The clue is an optional aid. Spending the turn's one retry
                    # on a malformed caption would cost the student the whole
                    # answer for a picture, so a bad clue is dropped, not retried.
                    try:
                        visual = drawn_clue(spoken)
                    except (ValueError, TypeError) as exc:
                        log.warning("dropping an unusable visual clue: %s", exc)
                        visual = None
                    if visual is not None:
                        visualizations = [visual]
                        context.last_visualizations = [*context.last_visualizations, visual][-3:]
                    elif spoken.visual_action == "reuse" and context.last_visualizations:
                        # Reuse used to emit nothing, so the brain pointed at a clue
                        # that was several turns up the scroll, or gone after a
                        # reload. Show it again beside the question about it.
                        visualizations = [context.last_visualizations[-1]]
                except SoftViolation as exc:
                    soft_failures += 1
                    # The tool error alone gets patched, not rewritten: the model
                    # keeps its definition and bolts a question on. Say in the
                    # policy itself what the rewrite must look like.
                    system += (
                        f"\n이전 초안은 폐기됐다: {exc} 이번 finish_turn의 feedback은 두 문장만 쓴다. "
                        "첫 문장은 개념을 정의하지 않는 짧은 힌트, 둘째 문장은 학생이 답할 수 있는 "
                        "질문이며 물음표로 끝난다."
                    )
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                except (ValueError, TypeError) as exc:
                    if failures >= MAX_FINISH_RETRIES:
                        raise LLMError("Voice LLM failed spoken-turn validation") from exc
                    failures += 1
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                else:
                    # Validate the entire turn before releasing text or irreversible
                    # audio, and only then let it into the conversation.
                    if on_token:
                        await on_token(reply)
                    level_before = context.hint_level
                    context.hint_level = brain.next_hint_level(
                        context.hint_level, spoken.student_state
                    )
                    log.info(
                        "voice turn student_state=%s hint_level=%d->%d soft_retries=%d "
                        "hard_retries=%d",
                        spoken.student_state,
                        level_before,
                        context.hint_level,
                        soft_failures,
                        failures,
                    )
                    context.append_history(question)
                    context.append_history({"role": "assistant", "content": reply})
                    from app.services.voice.session_store import external_brain_for

                    external_brain_for(
                        context.user_id,
                        context.course_id,
                        context.course_name,
                    ).schedule(context.history, source="realtime")
                    return VoiceBrainResult(
                        reply,
                        tools_used,
                        external_sources[:3],
                        visualizations,
                        turn.model_name,
                        spoken.visual_action,
                        spoken.visual_topic,
                        student_state=spoken.student_state,
                        hint_level=context.hint_level,
                    )
            elif call.name == "search_trusted_web":
                result = await brain.run_tool(context, call.name, call.arguments, timer)
                parsed = json.loads(result)
                external_sources = parsed.get("sources", [])
                if call.name not in tools_used:
                    tools_used.append(call.name)
            else:
                if failures >= MAX_FINISH_RETRIES:
                    raise LLMError("Voice LLM repeatedly selected an unavailable tool")
                failures += 1
                result = json.dumps(
                    {
                        "error": "Only search_trusted_web and finish_turn are "
                        "available. Course evidence is already preloaded."
                    }
                )
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

    raise RuntimeError("the assistant exceeded the tool-call round limit")
