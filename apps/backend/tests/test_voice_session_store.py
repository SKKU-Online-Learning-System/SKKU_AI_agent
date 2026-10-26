from types import SimpleNamespace

from app.services.voice import session_store


def _advance(monkeypatch, seconds: float) -> None:
    now = session_store.time.monotonic() + seconds
    monkeypatch.setattr(session_store.time, "monotonic", lambda: now)


def test_idle_context_is_evicted_but_pinned_and_busy_ones_stay(monkeypatch):
    idle = session_store.get_context("evict-idle", "course", "강의")
    pinned = session_store.get_context("evict-pinned", "course", "강의")
    session_store.pin_context("evict-pinned", "course")
    session_store._external_brains[("evict-idle", "course")] = SimpleNamespace(busy=True)
    try:
        _advance(monkeypatch, session_store.IDLE_TTL_SECONDS + 1)
        session_store.get_context("evict-other", "course", "강의")

        assert session_store.get_context("evict-idle", "course", "강의") is not idle
        assert session_store.get_context("evict-pinned", "course", "강의") is pinned
        # The busy assessor survives the sweep that dropped its context.
        assert ("evict-idle", "course") in session_store._external_brains
    finally:
        session_store.unpin_context("evict-pinned", "course")
        session_store._external_brains.pop(("evict-idle", "course"), None)


def test_unpin_restarts_the_idle_clock(monkeypatch):
    context = session_store.get_context("evict-unpin", "course", "강의")
    session_store.pin_context("evict-unpin", "course")
    _advance(monkeypatch, session_store.IDLE_TTL_SECONDS + 1)
    session_store.unpin_context("evict-unpin", "course")
    session_store.get_context("evict-other", "course", "강의")

    assert session_store.get_context("evict-unpin", "course", "강의") is context
