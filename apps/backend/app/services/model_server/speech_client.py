"""ASR/TTS client for the external CPU-orchestrated speech pipeline."""

from __future__ import annotations

import io
import wave
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.services.model_server.client import async_client


class SpeechError(RuntimeError):
    code = "SPEECH_SERVER_FAILED"


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str
    audio_duration_ms: int
    inference_ms: int


@dataclass(frozen=True)
class SynthesisResult:
    pcm: bytes
    sample_rate: int = 24000
    inference_ms: int | None = None
    audio_duration_ms: int | None = None


def _wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


class SpeechClient:
    """Thin, pooled client. It never loads ASR/TTS model weights locally."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.asr_client = async_client(
            settings.speech_base_url,
            settings.model_server_api_key,
            max(settings.asr_timeout_seconds, settings.tts_timeout_seconds),
        )
        self.tts_client = async_client(
            settings.tts_base_url or settings.speech_base_url,
            settings.model_server_api_key,
            settings.tts_timeout_seconds,
        )

    async def transcribe(
        self,
        pcm: bytes,
        *,
        sample_rate: int = 16000,
        language: str | None = None,
    ) -> TranscriptionResult:
        if not pcm:
            raise SpeechError("ASR 입력 오디오가 비어 있습니다.")
        wav = _wav_bytes(pcm, sample_rate)
        try:
            response = await self.asr_client.post(
                "v1/audio/transcriptions",
                files={"file": ("utterance.wav", wav, "audio/wav")},
                data={"language": language or self.settings.tts_language},
                timeout=self.settings.asr_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise SpeechError("ASR 서버가 발화를 처리하지 못했습니다.") from exc

        text = str(payload.get("text", "")).strip()
        if not text:
            raise SpeechError("ASR 서버가 빈 transcript를 반환했습니다.")
        return TranscriptionResult(
            text=text,
            language=str(payload.get("language", language or self.settings.tts_language)),
            audio_duration_ms=int(payload.get("audio_duration_ms", 0) or 0),
            inference_ms=int(payload.get("inference_ms", 0) or 0),
        )

    async def synthesize(
        self,
        text: str,
        *,
        speaker: str | None = None,
        language: str | None = None,
    ) -> SynthesisResult:
        text = text.strip()
        if not text:
            raise SpeechError("TTS 입력 텍스트가 비어 있습니다.")
        try:
            response = await self.tts_client.post(
                "v1/audio/speech",
                json={
                    "input": text,
                    "voice": speaker or self.settings.tts_speaker,
                    "language": language or self.settings.tts_language,
                    "response_format": "pcm",
                },
                timeout=self.settings.tts_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechError("TTS 서버가 음성을 생성하지 못했습니다.") from exc

        sample_rate = int(response.headers.get("X-Audio-Sample-Rate", "24000"))
        if sample_rate != 24000:
            raise SpeechError(f"지원하지 않는 TTS sample rate입니다: {sample_rate}")
        return SynthesisResult(
            pcm=response.content,
            sample_rate=sample_rate,
            inference_ms=_optional_int(response.headers.get("X-Inference-Ms")),
            audio_duration_ms=_optional_int(response.headers.get("X-Audio-Duration-Ms")),
        )


    async def synthesize_stream(
        self,
        text: str,
        *,
        speaker: str | None = None,
        language: str | None = None,
        hop_len: int | None = None,
    ) -> AsyncIterator[tuple[bytes, int]]:
        """Yield ``(pcm_chunk, sample_rate)`` as the TTS server produces them.

        The non-streaming :meth:`synthesize` buffers the whole utterance, which
        throws away the server's incremental output and pushes first-audio latency
        out to the full synthesis time.
        """
        text = text.strip()
        if not text:
            raise SpeechError("TTS 입력 텍스트가 비어 있습니다.")

        request = self.tts_client.build_request(
            "POST",
            "v1/audio/speech",
            json={
                "input": text,
                "voice": speaker or self.settings.tts_speaker,
                "language": language or self.settings.tts_language,
                "response_format": "pcm",
                "stream": True,
                **({"hop_len": hop_len} if hop_len else {}),
            },
            timeout=self.settings.tts_timeout_seconds,
        )
        try:
            response = await self.tts_client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise SpeechError("TTS 서버가 음성을 생성하지 못했습니다.") from exc

        try:
            if response.status_code >= 400:
                await response.aread()
                raise SpeechError(
                    f"TTS 서버가 {response.status_code}를 반환했습니다."
                )
            sample_rate = int(response.headers.get("X-Audio-Sample-Rate", "24000"))
            if sample_rate != 24000:
                raise SpeechError(f"지원하지 않는 TTS sample rate입니다: {sample_rate}")
            try:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk, sample_rate
            except httpx.HTTPError as exc:
                raise SpeechError("TTS 스트림이 중간에 끊겼습니다.") from exc
        finally:
            await response.aclose()


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
