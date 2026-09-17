"""Voice-profile wrapper around the existing COURSE AGENT brain.

The core RAG, memory, tool execution, prompts and policies stay in brain.py.
This module only runs the same tool loop with LLMService(profile="voice") and
canonical OpenAI tool messages for the local cascade transport.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.core.config import get_settings
from app.services.llm_service import LLMService
from app.services.voice import brain

log = logging.getLogger("voice.local-brain")


@dataclass(frozen=True)
class VoiceBrainResult:
    reply: str
    tools: list[str]
    sources: list[str]
    visualizations: list[dict]
    model_name: str


def clone_context(context: brain.VoiceContext) -> brain.VoiceContext:
    """Snapshot history so the existing WebSocket event pump remains owner of it."""
    return brain.VoiceContext(
        course_id=context.course_id,
        course_name=context.course_name,
        user_id=context.user_id,
        memory=context.memory,
        history=[dict(message) for message in context.history],
        last_material_sources=list(context.last_material_sources),
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
    system = brain.answer_instructions(context, mode, prefetched)
    tools = [
        tool
        for tool in brain.TOOLS
        if tool["function"]["name"] in {"search_trusted_web", "show_visualization"}
    ]
    if getattr(settings, "voice_trace_content", False):
        log.info(
            "voice llm input mode=%s transcript=%.4000s system=%.4000s history=%.8000r",
            mode,
            transcript,
            system,
            context.history,
        )

    for _ in range(brain.MAX_TOOL_ROUNDS):
        started_at = time.perf_counter()
        first_token_seen = False

        round_speakable = True

        async def stream_token(token: str) -> None:
            nonlocal first_token_seen
            if not first_token_seen:
                first_token_seen = True
                timer.timings_ms.setdefault(
                    "llm_ttft",
                    round((time.perf_counter() - started_at) * 1000),
                )
            if on_token:
                await on_token(token)
            # Only this round's text is a speech candidate, and only until the
            # round reveals itself as a tool round.
            if round_speakable and on_speech_delta:
                await on_speech_delta(token)

        async def tool_call_started() -> None:
            nonlocal round_speakable
            round_speakable = False
            if on_speech_rollback:
                await on_speech_rollback()

        turn = await llm.stream_tool_turn(
            system=system,
            messages=[*brain._conversation(context.history), *tool_messages],
            tools=tools,
            on_token=stream_token,
            on_tool_call_started=tool_call_started,
        )
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
            reply = turn.text.strip() or "답변을 생성하지 못했어요. 다시 질문해 주세요."
            if external_sources:
                reply = brain.for_speech(reply)
            context.append_history({"role": "assistant", "content": reply})
            from app.services.voice.session_store import external_brain_for

            external_brain_for(
                context.user_id,
                context.course_id,
                context.course_name,
            ).schedule(context.history, source="realtime")
            return VoiceBrainResult(
                reply=reply,
                tools=tools_used,
                sources=external_sources[:3],
                visualizations=visualizations,
                model_name=turn.model_name,
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

        results = await asyncio.gather(
            *(brain.run_tool(context, call.name, call.arguments, timer) for call in turn.tool_calls)
        )
        for call, result in zip(turn.tool_calls, results):
            if call.name not in tools_used:
                tools_used.append(call.name)
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                parsed = {"error": "tool returned invalid JSON"}
            if call.name == "search_trusted_web":
                external_sources = parsed.get("sources", []) if isinstance(parsed, dict) else []
            elif call.name == "show_visualization" and isinstance(parsed, dict) and "error" not in parsed:
                visualizations.append(parsed)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

    raise RuntimeError("the assistant exceeded the tool-call round limit")
