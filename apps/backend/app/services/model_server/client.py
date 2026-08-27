"""Shared HTTP connection pools and health checks for SKKU Model Server."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

import httpx

from app.core.config import Settings


class ModelServerError(RuntimeError):
    """A remote inference service could not complete a request."""


def _base_url(url: str) -> str:
    return f"{url.rstrip('/')}/"


def _headers(api_key: Optional[str]) -> dict[str, str]:
    key = (api_key or "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


@lru_cache(maxsize=16)
def shared_sync_client(base_url: str, api_key: str, timeout_seconds: float) -> httpx.Client:
    """Return a process-wide pooled synchronous client for one endpoint profile."""
    return httpx.Client(
        base_url=_base_url(base_url),
        headers=_headers(api_key),
        timeout=httpx.Timeout(timeout_seconds),
    )


@lru_cache(maxsize=16)
def shared_async_client(base_url: str, api_key: str, timeout_seconds: float) -> httpx.AsyncClient:
    """Return a process-wide pooled async client for one endpoint profile."""
    return httpx.AsyncClient(
        base_url=_base_url(base_url),
        headers=_headers(api_key),
        timeout=httpx.Timeout(timeout_seconds),
    )


def sync_client(base_url: str, api_key: Optional[str], timeout_seconds: float) -> httpx.Client:
    return shared_sync_client(base_url, (api_key or "").strip(), timeout_seconds)


def async_client(base_url: str, api_key: Optional[str], timeout_seconds: float) -> httpx.AsyncClient:
    return shared_async_client(base_url, (api_key or "").strip(), timeout_seconds)


@dataclass(frozen=True)
class ServiceHealth:
    available: bool
    detail: str = ""
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "detail": self.detail, "model": self.model}


@dataclass(frozen=True)
class VoiceModelServerHealth:
    voice_llm: ServiceHealth
    speech: ServiceHealth

    @property
    def available(self) -> bool:
        return self.voice_llm.available and self.speech.available

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "voice_llm": self.voice_llm.as_dict(),
            "speech": self.speech.as_dict(),
        }


@dataclass(frozen=True)
class ModelServerHealth:
    text_llm: ServiceHealth
    voice_llm: ServiceHealth
    speech: ServiceHealth

    @property
    def voice_available(self) -> bool:
        return self.voice_llm.available and self.speech.available

    @property
    def all_available(self) -> bool:
        return self.text_llm.available and self.voice_available

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "text_llm": self.text_llm.as_dict(),
            "voice_llm": self.voice_llm.as_dict(),
            "speech": self.speech.as_dict(),
        }


def _models_health(
    base_url: str,
    model: str,
    settings: Settings,
) -> ServiceHealth:
    try:
        client = sync_client(
            base_url,
            settings.model_server_api_key,
            settings.model_health_timeout_seconds,
        )
        response = client.get("models")
        response.raise_for_status()
        payload = response.json()
        models = [str(item.get("id", "")) for item in payload.get("data", [])]
        if model and models and model not in models:
            return ServiceHealth(False, "configured model is not being served", model)
        return ServiceHealth(True, "ok", model)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return ServiceHealth(False, type(exc).__name__, model)


def _speech_health(settings: Settings) -> ServiceHealth:
    try:
        client = sync_client(
            settings.speech_base_url,
            settings.model_server_api_key,
            settings.model_health_timeout_seconds,
        )
        response = client.get("health")
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ready"):
            return ServiceHealth(False, str(payload.get("error") or payload.get("status") or "not ready"))
        return ServiceHealth(True, "ok")
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return ServiceHealth(False, type(exc).__name__)


def check_voice_model_server_health(settings: Settings) -> VoiceModelServerHealth:
    """Check only services required by local cascade voice."""
    return VoiceModelServerHealth(
        voice_llm=_models_health(settings.voice_llm_base_url, settings.voice_llm_model, settings),
        speech=_speech_health(settings),
    )


def check_model_server_health(settings: Settings) -> ModelServerHealth:
    """Best-effort health snapshot; never prevents FastAPI from starting."""
    return ModelServerHealth(
        text_llm=_models_health(settings.text_llm_base_url, settings.text_llm_model, settings),
        voice_llm=_models_health(settings.voice_llm_base_url, settings.voice_llm_model, settings),
        speech=_speech_health(settings),
    )
