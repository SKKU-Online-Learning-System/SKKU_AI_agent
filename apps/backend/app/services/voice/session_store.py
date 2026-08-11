"""In-process voice sessions, one per (user, course) pair.

ponytail: process-local state. Move to Redis when the API runs on more than one
worker; conversation history is short-lived and cheap to rebuild, so a restart
only costs the current turn's context.
"""

from __future__ import annotations

from threading import RLock

from app.core.config import get_settings
from app.services.voice.brain import VoiceContext
from app.services.voice.moss_memory import MossMemoryStore

# Reentrant: get_context() calls memory_store() while already holding the lock.
_lock = RLock()
_contexts: dict[tuple[str, str], VoiceContext] = {}
_memories: dict[str, MossMemoryStore] = {}


def memory_store(user_id: str) -> MossMemoryStore:
    """Return the shared weak-concept store for one learner."""
    with _lock:
        store = _memories.get(user_id)
        if store is None:
            store = MossMemoryStore(student_id=user_id)
            _memories[user_id] = store
        return store


def get_context(user_id: str, course_id: str, course_name: str) -> VoiceContext:
    """Return (creating if needed) the session state for one learner and course."""
    key = (user_id, course_id)
    with _lock:
        context = _contexts.get(key)
        if context is None:
            context = VoiceContext(
                course_id=course_id,
                course_name=course_name,
                user_id=user_id,
                memory=memory_store(user_id),
            )
            _contexts[key] = context
        else:
            context.course_name = course_name
        return context


def reset_context(user_id: str, course_id: str) -> None:
    """Clear the conversation history for one learner and course."""
    with _lock:
        context = _contexts.get((user_id, course_id))
    if context is not None:
        context.reset()


def is_voice_configured() -> bool:
    """Whether the xAI credentials needed for the voice agent are present."""
    return get_settings().is_voice_configured


async def shutdown() -> None:
    """Flush every learner's pending weak-concept sync."""
    with _lock:
        stores = list(_memories.values())
    for store in stores:
        try:
            await store.close()
        except Exception:  # pragma: no cover - best effort on shutdown
            pass
