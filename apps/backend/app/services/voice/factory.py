"""Provider-neutral realtime transport factory and availability checks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.core.config import Settings, get_settings
from app.services.model_server.client import check_voice_model_server_health
from app.services.voice.brain import VoiceContext
from app.services.voice.grok_live import GrokTransport
from app.services.voice.local_cascade import LocalCascadeTransport
from app.services.voice.transport import Transport


@dataclass(frozen=True)
class VoiceAvailability:
    enabled: bool
    provider: str
    services: dict[str, dict] = field(default_factory=dict)
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "services": self.services,
            "detail": self.detail,
        }


def get_voice_availability(settings: Settings | None = None) -> VoiceAvailability:
    """Return whether the selected voice provider is currently usable."""
    settings = settings or get_settings()
    if not settings.is_voice_configured:
        return VoiceAvailability(False, settings.voice_provider, detail="not configured")
    if settings.voice_provider == "grok":
        return VoiceAvailability(True, "grok")

    health = check_voice_model_server_health(settings)
    return VoiceAvailability(
        health.available,
        settings.voice_provider,
        services=health.as_dict(),
        detail="ok" if health.available else "model server unavailable",
    )


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
    """Select the configured provider without exposing implementation in the API route."""
    settings = settings or get_settings()
    if settings.voice_provider == "grok":
        transport = GrokTransport(
            instructions=instructions,
            tools=tools,
            run_tool=run_tool,
            refresh_instructions=refresh_instructions,
            schedule_assessment=schedule_assessment,
        )
        # Metadata is consumed generically by route-side ChatLog persistence.
        transport.provider_name = "xai"  # type: ignore[attr-defined]
        transport.model_name = settings.grok_voice_model  # type: ignore[attr-defined]
        return transport
    return LocalCascadeTransport(
        context=context,
        mode=mode,
        settings=settings,
    )
