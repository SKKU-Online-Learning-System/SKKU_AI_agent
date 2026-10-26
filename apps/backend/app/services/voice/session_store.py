"""In-process voice sessions, one per (user, course) pair.

ponytail: process-local state. Move to Redis when the API runs on more than one
worker; conversation history is short-lived and cheap to rebuild, so a restart
only costs the current turn's context.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from threading import RLock

from app.core.config import get_settings
from app.services.voice.brain import VoiceContext
from app.services.voice.external_brain import ExternalBrain
from app.services.voice.moss_memory import MossMemoryStore

log = logging.getLogger("voice.session_store")

# Reentrant: get_context() calls memory_store() while already holding the lock.
_lock = RLock()
_contexts: dict[tuple[str, str], VoiceContext] = {}
_memories: dict[str, MossMemoryStore] = {}
_external_brains: dict[tuple[str, str], ExternalBrain] = {}
_last_used: dict[tuple[str, str], float] = {}
# Keys an open voice stream is holding; never evicted while the socket lives.
_pinned: Counter[tuple[str, str]] = Counter()

# A context untouched this long is dropped. Its conversation is in ChatLog, and
# reopening it from 대화 이력 rehydrates it, so eviction costs nothing a student
# can see -- but without it every (learner, course) pair, recent images
# included, stays in memory until the process restarts.
IDLE_TTL_SECONDS = 6 * 60 * 60


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
        now = time.monotonic()
        _evict_idle(now)
        _last_used[key] = now
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


def _evict_idle(now: float) -> None:
    """Drop contexts idle past the TTL. Caller holds ``_lock``."""
    for key, used in list(_last_used.items()):
        if now - used <= IDLE_TTL_SECONDS or _pinned[key]:
            continue
        _contexts.pop(key, None)
        worker = _external_brains.get(key)
        # An assessor still writing weak concepts keeps its key for the next sweep:
        # the event loop holds its tasks only weakly.
        if worker is not None and worker.busy:
            continue
        _external_brains.pop(key, None)
        del _last_used[key]


def pin_context(user_id: str, course_id: str) -> None:
    """Keep a context alive while a voice stream holds it."""
    with _lock:
        _pinned[(user_id, course_id)] += 1


def unpin_context(user_id: str, course_id: str) -> None:
    """Release a pin; the idle clock restarts from now."""
    key = (user_id, course_id)
    with _lock:
        _pinned[key] -= 1
        if _pinned[key] <= 0:
            del _pinned[key]
        if key in _contexts:
            _last_used[key] = time.monotonic()


def external_brain_for(user_id: str, course_id: str, course_name: str) -> ExternalBrain:
    """Return the background learning assessor for one learner and course."""
    key = (user_id, course_id)
    with _lock:
        worker = _external_brains.get(key)
        if worker is None:
            worker = ExternalBrain(memory_store(user_id), course_name)
            _external_brains[key] = worker
        else:
            worker.course_name = course_name
        return worker


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
        workers = list(_external_brains.values())
        stores = list(_memories.values())
    for worker in workers:
        try:
            await worker.flush()
        except Exception:  # pragma: no cover - best effort on shutdown
            log.exception("weak-concept assessment lost on shutdown")
    for store in stores:
        try:
            await store.close()
        except Exception:  # pragma: no cover - best effort on shutdown
            log.exception("weak-concept memory sync lost on shutdown")
