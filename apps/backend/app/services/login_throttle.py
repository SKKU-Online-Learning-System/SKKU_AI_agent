"""Failed-login throttling, so a password cannot be guessed at request speed.

Counted per account *and* client address. Per account alone, anyone who knows a
professor's email could keep them locked out with five wrong passwords every
fifteen minutes; per address alone, a lecture hall behind one NAT would share a
budget. Only failures against accounts that exist are counted (the route checks),
so made-up addresses cannot fill the table, and a success clears the account's
record from that address.

ponytail: process-local, like the voice session store. Move to Redis with it
when the API runs on more than one worker. Behind a reverse proxy every client
shares the proxy's address, which degrades this to per-account counting.
"""

from __future__ import annotations

import math
import time
from collections import deque
from threading import Lock

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5
# Bounded no matter what is sent: the oldest record goes first when full.
MAX_TRACKED = 10_000

_lock = Lock()
_failures: dict[str, deque[float]] = {}


def _key(email: str, address: str) -> str:
    return f"{email.strip().lower()}|{address}"


def _recent(key: str, now: float) -> deque[float]:
    attempts = _failures.get(key)
    if attempts is None:
        return deque()
    while attempts and now - attempts[0] >= WINDOW_SECONDS:
        attempts.popleft()
    if not attempts:
        del _failures[key]
    return attempts


def retry_after(email: str, address: str) -> int:
    """Seconds until another attempt is allowed; 0 when it is allowed now."""
    now = time.monotonic()
    with _lock:
        attempts = _recent(_key(email, address), now)
        if len(attempts) < MAX_FAILURES:
            return 0
        return max(1, math.ceil(WINDOW_SECONDS - (now - attempts[-MAX_FAILURES])))


def record_failure(email: str, address: str) -> None:
    now = time.monotonic()
    key = _key(email, address)
    with _lock:
        attempts = _recent(key, now)
        if not attempts:
            if len(_failures) >= MAX_TRACKED:
                del _failures[next(iter(_failures))]
            attempts = _failures[key] = deque()
        attempts.append(now)


def record_success(email: str, address: str) -> None:
    with _lock:
        _failures.pop(_key(email, address), None)


def reset() -> None:
    with _lock:
        _failures.clear()
