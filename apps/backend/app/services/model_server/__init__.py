"""Clients for the external SKKU GPU Model Server.

This package contains HTTP clients only. Model weights and GPU runtimes belong
exclusively to SKKU_AI_model_server.
"""

from .client import ModelServerError, ModelServerHealth, check_model_server_health
from .speech_client import SpeechClient, SpeechError, SynthesisResult, TranscriptionResult

__all__ = [
    "ModelServerError",
    "ModelServerHealth",
    "SpeechClient",
    "SpeechError",
    "SynthesisResult",
    "TranscriptionResult",
    "check_model_server_health",
]
