"""Application-side endpointing for fixed-size browser PCM frames.

The local cascade uses Silero VAD on the application CPU. Browser input stays
PCM16 mono 16 kHz in 20 ms frames; the adapter internally batches samples into
Silero's 16 kHz inference windows while TurnDetector keeps the existing prefix,
onset debounce and silence endpoint semantics.
"""

from __future__ import annotations

import io
import logging
import sys
import wave
from array import array
from collections import deque

from app.core.config import get_settings

log = logging.getLogger("voice.turn-detector")

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2
SILERO_SAMPLES = 512
SILERO_BYTES = SILERO_SAMPLES * 2

_settings = get_settings()
SILENCE_MS = _settings.silence_ms
PREFIX_MS = _settings.prefix_ms
MIN_SPEECH_MS = _settings.min_speech_ms
VAD_AGGRESSIVENESS = _settings.vad_aggressiveness  # legacy compatibility only

# Onset debounce: declare SPEAKING only after 3 speech frames in the last 5.
ONSET_FRAMES, ONSET_WINDOW = 3, 5


class SileroVad:
    """Small stateful adapter from 20 ms PCM frames to Silero ONNX probabilities."""

    def __init__(self, threshold: float | None = None) -> None:
        try:
            import torch
            from silero_vad import load_silero_vad
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError(
                "Silero VAD runtime is missing. Install the backend 'vad' extra."
            ) from exc
        self._torch = torch
        self.threshold = get_settings().vad_threshold if threshold is None else threshold
        self.model = load_silero_vad(onnx=True)
        self._buffer = bytearray()
        self._last_is_speech = False

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"Silero VAD expects {SAMPLE_RATE} Hz audio")
        self._buffer.extend(frame)
        while len(self._buffer) >= SILERO_BYTES:
            chunk = bytes(self._buffer[:SILERO_BYTES])
            del self._buffer[:SILERO_BYTES]
            samples = array("h")
            samples.frombytes(chunk)
            if sys.byteorder != "little":
                samples.byteswap()
            tensor = self._torch.tensor(samples, dtype=self._torch.float32) / 32768.0
            probability = float(self.model(tensor, SAMPLE_RATE).item())
            self._last_is_speech = probability >= self.threshold
        return self._last_is_speech

    def reset_states(self) -> None:
        self._buffer.clear()
        self._last_is_speech = False
        reset = getattr(self.model, "reset_states", None)
        if callable(reset):
            reset()


class TurnDetector:
    """Detect complete speech turns from fixed-size PCM frames."""

    def __init__(self, vad=None) -> None:
        self.vad = vad or SileroVad()
        self.reset()

    def reset(self) -> None:
        self.speaking = False
        self._frames: list[bytes] = []
        self._prefix: deque[bytes] = deque(maxlen=max(PREFIX_MS // FRAME_MS, 1))
        self._onset: deque[bool] = deque(maxlen=ONSET_WINDOW)
        self._quiet_ms = 0
        self._speech_ms = 0
        reset = getattr(self.vad, "reset_states", None)
        if callable(reset):
            reset()

    def feed(self, frame: bytes) -> bytes | None:
        """Consume exactly one 20 ms PCM16 mono 16 kHz frame."""
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"expected {FRAME_BYTES} PCM bytes, got {len(frame)}")
        is_speech = bool(self.vad.is_speech(frame, SAMPLE_RATE))

        if not self.speaking:
            self._prefix.append(frame)
            self._onset.append(is_speech)
            if sum(self._onset) >= ONSET_FRAMES:
                self.speaking = True
                self._frames = list(self._prefix)
                self._speech_ms = sum(self._onset) * FRAME_MS
                self._quiet_ms = 0
                log.info("[SPEECH START]")
            return None

        self._frames.append(frame)
        if is_speech:
            self._speech_ms += FRAME_MS
            self._quiet_ms = 0
        else:
            self._quiet_ms += FRAME_MS

        if self._quiet_ms < SILENCE_MS:
            return None

        utterance = b"".join(self._frames)
        speech_ms = self._speech_ms
        duration_s = len(self._frames) * FRAME_MS / 1000
        self.reset()

        if speech_ms < MIN_SPEECH_MS:
            log.info("[DISCARDED] %d ms of speech — too short for a turn", speech_ms)
            return None

        log.info("[SPEECH END after %.1fs -> pipeline]", duration_s)
        return utterance


def wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw little-endian PCM16 in mono 16 kHz WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm)
    return buf.getvalue()
