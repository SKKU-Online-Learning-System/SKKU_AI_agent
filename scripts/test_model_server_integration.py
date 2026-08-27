#!/usr/bin/env python3
"""Optional live smoke test for SKKU_AI_model_server.

This script is intentionally outside the unit-test suite. It only uses external
HTTP APIs and never loads Qwen/ASR/TTS weights in the application repository.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.services.llm_service import ChatMessage, LLMService  # noqa: E402
from app.services.model_server import SpeechClient, check_model_server_health  # noqa: E402


def _read_pcm16_mono_16k(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 16000:
            raise ValueError("sample WAV must be PCM16 mono 16 kHz")
        return wav.readframes(wav.getnframes())


async def _speech_flow(wav_path: Path) -> None:
    settings = get_settings()
    speech = SpeechClient(settings)
    pcm = _read_pcm16_mono_16k(wav_path)
    transcription = await speech.transcribe(pcm, sample_rate=16000)
    print(
        "ASR:",
        {
            "language": transcription.language,
            "audio_duration_ms": transcription.audio_duration_ms,
            "inference_ms": transcription.inference_ms,
            "text": transcription.text,
        },
    )

    voice_response = LLMService(settings, profile="voice").generate_answer(
        [ChatMessage("user", transcription.text)]
    )
    print("Voice LLM:", voice_response.model_name, voice_response.answer)

    audio = await speech.synthesize(
        voice_response.answer,
        speaker=settings.tts_speaker,
        language=settings.tts_language,
    )
    print(
        "TTS:",
        {
            "pcm_bytes": len(audio.pcm),
            "sample_rate": audio.sample_rate,
            "channels": 1,
            "sample_width_bits": 16,
            "inference_ms": audio.inference_ms,
            "audio_duration_ms": audio.audio_duration_ms,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wav",
        type=Path,
        help="Optional Korean PCM16 mono 16 kHz WAV for the ASR -> Voice LLM -> TTS leg.",
    )
    args = parser.parse_args()
    settings = get_settings()

    health = check_model_server_health(settings)
    print("Model Server health:", health.as_dict())
    if not health.text_llm.available:
        print("Text Qwen is unavailable; stopping live smoke test.")
        return 2

    text = LLMService(settings, profile="text").generate_answer(
        [ChatMessage("user", "가상 메모리가 뭐야?")]
    )
    print("Text LLM:", text.model_name, text.answer)

    if args.wav is None:
        print("Speech leg skipped: pass --wav <pcm16-mono-16k.wav> to test ASR/Voice/TTS.")
        return 0
    if not health.voice_available:
        print("Voice LLM or Speech Server is unavailable; speech leg not executed.")
        return 3

    asyncio.run(_speech_flow(args.wav))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
