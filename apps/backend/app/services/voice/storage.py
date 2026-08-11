"""On-disk locations for voice-agent state that is not in PostgreSQL."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import get_settings

_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def voice_storage_dir() -> Path:
    """Return (and create) the root directory for voice-agent side files."""
    path = Path(get_settings().upload_dir) / "voice"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_key(value: str) -> str:
    """Turn an identifier into a filename-safe key."""
    cleaned = _UNSAFE_PATH_CHARS.sub("_", (value or "").strip())
    if not cleaned:
        raise ValueError("identifier is required")
    return cleaned[:120]
