"""Week 3 endpointing: turn detection from fixed-size PCM frames.

The realtime Grok transport uses server-side VAD, so this detector is not on
the default hands-free path. It is kept because it is the fallback for
providers without server VAD, and because it is fully deterministic under test
(inject a stub ``vad`` with a scripted ``is_speech``).
"""

from __future__ import annotations

import io
import logging
import wave
from collections import deque

from app.core.config import get_settings

log = logging.getLogger("voice.turn-detector")

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE * FRAME_MS // 1000 * 2

_settings = get_settings()
SILENCE_MS = _settings.silence_ms
PREFIX_MS = _settings.prefix_ms
MIN_SPEECH_MS = _settings.min_speech_ms
VAD_AGGRESSIVENESS = _settings.vad_aggressiveness

# Onset debounce: declare SPEAKING only after 3 speech frames in the last 5.
ONSET_FRAMES, ONSET_WINDOW = 3, 5


class TurnDetector:
    """Detect complete speech turns from fixed-size PCM frames."""

    def __init__(self, vad=None) -> None:
        """Create detector.

        Args:
            vad: Optional VAD-compatible detector; a stub keeps tests deterministic.
        """
        if vad is None:
            # Imported lazily: webrtcvad is only needed for this fallback path.
            import webrtcvad

            vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.vad = vad
        self.reset()

    def reset(self) -> None:
        """Clear accumulated turn state."""
        self.speaking = False
        self._frames: list[bytes] = []
        self._prefix: deque[bytes] = deque(maxlen=PREFIX_MS // FRAME_MS)
        self._onset: deque[bool] = deque(maxlen=ONSET_WINDOW)
        self._quiet_ms = 0
        self._speech_ms = 0

    def feed(self, frame: bytes) -> bytes | None:
        """Consume one PCM frame.

        Args:
            frame: Exactly 20 ms of mono 16 kHz int16 PCM.

        Returns:
            Complete PCM utterance at endpoint, otherwise None.
        """
        is_speech = self.vad.is_speech(frame, SAMPLE_RATE)

        if not self.speaking:
            # IDLE: remember recent audio (prefix padding) and debounce onset.
            self._prefix.append(frame)
            self._onset.append(is_speech)
            if sum(self._onset) >= ONSET_FRAMES:
                self.speaking = True
                self._frames = list(self._prefix)  # first syllables survive
                self._speech_ms = sum(self._onset) * FRAME_MS
                self._quiet_ms = 0
                log.info("[SPEECH START]")
            return None

        # SPEAKING: keep everything (pauses are part of the audio), count
        # trailing silence, and commit the turn at SILENCE_MS.
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
            log.info("[DISCARDED] %d ms of speech — a cough, not a turn", speech_ms)
            return None

        log.info("[SPEECH END after %.1fs -> pipeline]", duration_s)
        return utterance


def wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw PCM in WAV.

    Args:
        pcm: Raw little-endian int16 samples.

    Returns:
        Mono 16 kHz WAV bytes.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm)
    return buf.getvalue()
