"""Bound password checks per address, account, and account/address pair."""

import math
import time
from collections import OrderedDict, deque
from threading import Lock

WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 5
MAX_TRACKED = 10_000

_lock = Lock()
_attempts: OrderedDict[tuple, deque[float]] = OrderedDict()


def claim_attempt(email: str, address: str) -> int:
    """Reserve a password check before doing Argon2 work, for any email."""
    now = time.monotonic()
    email = email.strip().lower()
    limits = (
        (("all",), 600, 60),
        (("ip", address), 120, 60),
        (("account", email), 20, WINDOW_SECONDS),
        (("pair", email, address), MAX_FAILURES, WINDOW_SECONDS),
    )
    with _lock:
        entries = []
        for key, limit, window in limits:
            attempts = _attempts.get(key)
            if attempts is None:
                attempts = deque()
            while attempts and now - attempts[0] >= window:
                attempts.popleft()
            if len(attempts) >= limit:
                return max(1, math.ceil(window - (now - attempts[0])))
            entries.append((key, attempts))
        for key, attempts in entries:
            attempts.append(now)
            _attempts[key] = attempts
            _attempts.move_to_end(key)
        while len(_attempts) > MAX_TRACKED:
            _attempts.popitem(last=False)
    return 0


def record_success(email: str, address: str) -> None:
    with _lock:
        _attempts.pop(("pair", email.strip().lower(), address), None)


def reset() -> None:
    with _lock:
        _attempts.clear()
