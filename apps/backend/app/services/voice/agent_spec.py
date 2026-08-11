"""Provider-neutral voice-agent persona and tool adapter."""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from app.services.voice.brain import (
    MODE_PROMPTS,
    SYSTEM_PROMPT,
    TOOLS,
    StageTimer,
    VoiceContext,
)
from app.services.voice.brain import run_tool as run_brain_tool

VOICE_FILLER_PROMPT = """
# Voice-only filler
Immediately before the first tool call, say exactly one short Korean filler.
Either briefly confirm the student's topic, such as '소프트맥스 연산에 대해
물으신 거 맞죠?', or say '잠시만요. 강의 자료를 찾아볼게요.' Do not include
equations, source details, or the answer. Never repeat the filler after the tools
finish.
""".strip()


def persona(course_name: str, mode: str) -> str:
    """Return the shared teaching persona for one voice session."""
    course_prompt = (
        f"# Course\nThis session belongs to the Sungkyunkwan University course "
        f"'{course_name}'. Course-material search is limited to that course."
    )
    return "\n\n".join(
        (
            SYSTEM_PROMPT,
            course_prompt,
            VOICE_FILLER_PROMPT,
            MODE_PROMPTS.get(mode, MODE_PROMPTS["socratic"]),
        )
    )


def json_schemas() -> list[dict]:
    """Convert the chat tool definitions to realtime function schemas."""
    return [{"type": "function", **tool["function"]} for tool in TOOLS]


def tool_runner(context: VoiceContext) -> Callable[[str, dict], Awaitable[object]]:
    """Bind the shared tool dispatcher to one course-scoped session."""

    async def run(name: str, args: dict) -> object:
        return json.loads(await run_brain_tool(context, name, args, StageTimer()))

    return run
