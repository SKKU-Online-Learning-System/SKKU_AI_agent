"""Voice-profile wrapper around the existing COURSE AGENT brain.

The core RAG, memory, tool execution, prompts and policies stay in brain.py.
The voice loop requests a bounded finish_turn and validates its speech and visual
before releasing either. Search and visualization still use the shared brain tools.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.services.llm_service import LLMError, LLMService, ToolCallRequest
from app.services.voice import brain

log = logging.getLogger("voice.local-brain")
MAX_FINISH_RETRIES = 1
SOCIAL_INPUT = re.compile(r"안녕|고마|감사|그만|여기까지|기다려|잠깐")


class SpokenTurn(BaseModel):
    """One bounded utterance and its visual clue, validated before any speech."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intent: Literal["teach", "social"] = Field(
        description="social for greeting, thanks, goodbye or pause; otherwise teach"
    )
    feedback: str = Field(
        max_length=120,
        pattern=r"^[^?？]*$",
        description="One short declarative Korean clue or feedback sentence. No questions.",
    )
    question: str = Field(
        default="",
        max_length=100,
        description="One easy reasoning question ending in ?; empty for social turns",
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


def validate_spoken_turn(args: dict, context: brain.VoiceContext, transcript: str) -> SpokenTurn:
    # ponytail: deterministic checks catch malformed/echoed speech, not semantic teaching errors;
    # keep multi-topic live evaluations for difficulty, grounding and answer leakage.
    normalized = dict(args)
    social_input = bool(SOCIAL_INPUT.search(transcript))
    if social_input:
        normalized.update(intent="social", question="", visual_action="none", visual_topic="")
        if "?" in str(normalized.get("feedback", "")):
            normalized["feedback"] = (
                "안녕하세요. 함께 공부해 봐요." if "안녕" in transcript else "네, 알겠습니다."
            )
    elif normalized.get("intent") == "social":
        normalized["intent"] = "teach"

    question_text = str(normalized.get("question", "")).strip()
    if normalized.get("intent") == "teach":
        if not question_text:
            normalized["question"] = "같은 원리를 새로운 예에 적용하면 어떻게 달라질까요?"
        elif not question_text.endswith(("?", "？")):
            normalized["question"] = question_text + "?"
        if normalized.get("visual_action") == "none":
            normalized["visual_action"] = "show"
            normalized["visual_topic"] = transcript[:80]
    turn = SpokenTurn.model_validate(normalized)

    def compact(text):
        return re.sub(r"[\W_]+", "", text).casefold()

    previous = next(
        (m["content"].strip() for m in reversed(context.history) if m.get("role") == "assistant"),
        "",
    )
    if previous and len(compact(previous)) >= 12 and turn.feedback.startswith(previous):
        feedback = turn.feedback[len(previous) :].lstrip(" ,.;:!?。！？")
        if not feedback:
            raise ValueError("Do not repeat your previous turn; respond to the student's answer.")
        turn = turn.model_copy(update={"feedback": feedback})

    reply = f"{turn.feedback.strip()} {turn.question.strip()}".strip()
    answer, question = compact(reply), compact(transcript)
    if not answer or (
        turn.intent == "teach"
        and question
        and (compact(turn.feedback) == question or not answer.replace(question, ""))
    ):
        raise ValueError("Do not echo the student; offer a concrete clue and a new question.")
    previous_answer = compact(previous)
    if turn.intent == "teach" and previous_answer and (
        answer == previous_answer or (len(previous_answer) >= 12 and previous_answer in answer)
    ):
        raise ValueError("Do not repeat your previous turn; respond to the student's answer.")
    if "?" in turn.feedback or "？" in turn.feedback:
        raise ValueError("Put the single question in question, not feedback.")
    if turn.intent == "teach":
        if (
            not turn.question.endswith(("?", "？"))
            or sum(turn.question.count(mark) for mark in ("?", "？")) != 1
        ):
            raise ValueError("Teaching requires exactly one reasoning question ending in ?.")
    elif turn.question or turn.visual_action != "none":
        raise ValueError("Social turns need no question or visual.")
    if re.search(r"궁금하신가요|설명해\s*드릴까요|이해되셨나요|뭐라고 생각", reply):
        raise ValueError(
            "Ask an accessible comparison or prediction, not permission or a definition quiz."
        )
    if (turn.visual_action == "show") != bool(turn.visual_topic):
        raise ValueError("Provide visual_topic only when requesting a new visual.")
    if turn.visual_action == "reuse" and not context.last_visualizations:
        raise ValueError("No previous visual is available to reuse.")
    return turn


def recover_plain_turn(text: str, context: brain.VoiceContext, transcript: str) -> SpokenTurn:
    """Salvage a final forced-tool miss only when it already fits the speech contract."""
    cleaned = text.strip().strip("_*` ")
    if SOCIAL_INPUT.search(transcript):
        arguments = {"intent": "social", "feedback": cleaned, "visual_action": "none"}
    else:
        parts = re.split(r"(?<=[.!])\s+", cleaned)
        questions = [part.strip() for part in re.split(r"[?？]", parts[-1]) if part.strip()]
        if len(questions) > 1 and parts[-1].endswith(("?", "？")):
            parts[-1] = questions[-1] + "?"
            parts.insert(-1, ". ".join(questions[:-1]) + ".")

        if len(parts) < 2:
            raise ValueError("Plain-text recovery requires feedback followed by one question.")
        arguments = {
            "intent": "teach",
            "feedback": " ".join(parts[:-1]),
            "question": parts[-1],
            "visual_action": "none",
        }
    return validate_spoken_turn(arguments, context, transcript)


@dataclass(frozen=True)
class VoiceBrainResult:
    reply: str
    tools: list[str]
    sources: list[str]
    visualizations: list[dict]
    model_name: str
    visual_action: Literal["show", "reuse", "none"] = "none"
    visual_topic: str = ""


def clone_context(context: brain.VoiceContext) -> brain.VoiceContext:
    """Snapshot history so the existing WebSocket event pump remains owner of it."""
    return brain.VoiceContext(
        course_id=context.course_id,
        course_name=context.course_name,
        user_id=context.user_id,
        memory=context.memory,
        history=[dict(message) for message in context.history],
        last_material_sources=list(context.last_material_sources),
        last_visualizations=list(context.last_visualizations),
        chat_session_id=context.chat_session_id,
    )


async def think_voice(
    context: brain.VoiceContext,
    transcript: str,
    timer: brain.StageTimer,
    mode: str,
    on_token: Callable[[str], Awaitable[None]] | None = None,
    on_speech_delta: Callable[[str], Awaitable[None]] | None = None,
    on_speech_rollback: Callable[[], Awaitable[None]] | None = None,
) -> VoiceBrainResult:
    """Run the existing brain policy with the Qwen voice profile."""
    context.append_history({"role": "user", "content": transcript})
    context.last_material_sources = []
    settings = get_settings()
    llm = LLMService(settings, profile="voice")
    tool_messages: list[dict] = []
    tools_used: list[str] = []
    external_sources: list[str] = []
    visualizations: list[dict] = []

    prefetched = await brain.prefetch_context(context, transcript, timer)
    system = brain.answer_instructions(context, mode, prefetched) + (
        "\nSubmit the final utterance through finish_turn, never plain text. "
        "Set visual_action and a short visual_topic; another worker draws new visuals. "
        "Never refer to a new visual as already visible. "
        "For a beginner, give a familiar situation before an easy two-choice comparison. "
        "After a wrong answer, give a counterexample without stating the correction. "
        "After a correct answer, ask a NEW application, not the same answer again. "
        "Put all questions in question; feedback is a statement, never a question. "
        "Use search results before submitting finish_turn alone."
    )
    tools = [tool for tool in brain.TOOLS if tool["function"]["name"] == "search_trusted_web"]
    tools.append(
        {
            "type": "function",
            "function": {
                "name": "finish_turn",
                "description": "Submit the Korean Socratic utterance and visual clue.",
                "parameters": SpokenTurn.model_json_schema(),
            },
        }
    )
    if getattr(settings, "voice_trace_content", False):
        log.info(
            "voice llm input mode=%s transcript=%.4000s system=%.4000s history=%.8000r",
            mode,
            transcript,
            system,
            context.history,
        )

    failures = 0
    for _ in range(brain.MAX_TOOL_ROUNDS):
        started_at = time.perf_counter()
        try:
            turn = await llm.stream_tool_turn(
                system=system,
                messages=[*brain._conversation(context.history), *tool_messages],
                tools=tools[-1:] if failures else tools,
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
            if failures >= MAX_FINISH_RETRIES:
                try:
                    recovered = recover_plain_turn(turn.text, context, transcript)
                except (ValueError, TypeError) as exc:
                    log.warning("using safe voice fallback after invalid plain turn: %s", exc)
                    if SOCIAL_INPUT.search(transcript):
                        fallback = {
                            "intent": "social",
                            "feedback": "네, 알겠습니다.",
                            "visual_action": "none",
                        }
                    else:
                        fallback = {
                            "intent": "teach",
                            "feedback": "좋아요, 방금 생각을 한 단계 더 적용해 볼게요.",
                            "question": "같은 원리를 새로운 예에 적용하면 결과가 어떻게 달라질까요?",
                            "visual_action": "none",
                        }
                    recovered = validate_spoken_turn(fallback, context, transcript)
                turn = type(turn)(
                    "",
                    [ToolCallRequest("recovered", "finish_turn", recovered.model_dump())],
                    turn.model_name,
                )
            else:
                failures += 1
                system += "\nUse finish_turn; plain text is not accepted."
                continue

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
                except (ValueError, TypeError) as exc:
                    if failures >= MAX_FINISH_RETRIES:
                        raise LLMError("Voice LLM failed spoken-turn validation") from exc
                    failures += 1
                    result = json.dumps({"error": str(exc)}, ensure_ascii=False)
                else:
                    # Validate the entire turn before releasing text or irreversible audio.
                    timer.timings_ms["llm_ttft"] = timer.timings_ms["llm"]
                    if on_token:
                        await on_token(reply)
                    if on_speech_delta:
                        await on_speech_delta(brain.for_speech(reply))
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
