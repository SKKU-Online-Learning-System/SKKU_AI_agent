"""Provider-neutral realtime transport factory."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.config import Settings, get_settings
from app.services.voice.brain import VoiceContext
from app.services.voice.grok_live import GrokTransport
from app.services.voice.local_cascade import LocalCascadeTransport
from app.services.voice.transport import Transport


def create_voice_transport(
    *,
    context: VoiceContext,
    mode: str,
    instructions: str,
    tools: list[dict],
    run_tool: Callable[[str, dict], Awaitable[object]],
    refresh_instructions: Callable[[], Awaitable[str]] | None = None,
    schedule_assessment: Callable[[list[dict]], object] | None = None,
    settings: Settings | None = None,
) -> Transport:
    """Select the configured provider without exposing it to the API route."""
    settings = settings or get_settings()
    if settings.voice_provider == "grok":
        return GrokTransport(
            instructions=instructions,
            tools=tools,
            run_tool=run_tool,
            refresh_instructions=refresh_instructions,
            schedule_assessment=schedule_assessment,
        )
    return LocalCascadeTransport(
        context=context,
        mode=mode,
        settings=settings,
    )
