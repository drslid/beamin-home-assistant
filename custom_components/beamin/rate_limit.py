"""In-memory rate limiting and lockouts for BeamIn."""

from __future__ import annotations

from collections import deque
from ipaddress import IPv6Address, IPv6Network, ip_address

# Bounds memory if an attacker rotates source addresses.
MAX_TRACKED_KEYS = 4096


def ip_key(ip: str) -> str:
    """Return the rate-limit key of an address: the address, or its /64 for IPv6.

    One IPv6 subscriber usually owns a whole /64, so per-address limits would not
    hold anyone back.
    """
    try:
        address = ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(IPv6Network((address, 64), strict=False))
    return str(address)


class SlidingWindowLimiter:
    """Allow at most `limit` events per key within a sliding `window` (seconds)."""

    def __init__(self, limit: int, window: float) -> None:
        """Initialize the limiter."""
        self._limit = limit
        self._window = window
        self._events: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float) -> float | None:
        """Record an event; return the seconds to wait instead if over the limit."""
        events = self._events.get(key)
        if events is None:
            if len(self._events) >= MAX_TRACKED_KEYS:
                self._prune(now)
            events = self._events[key] = deque()
        while events and events[0] <= now - self._window:
            events.popleft()
        if len(events) >= self._limit:
            return events[0] + self._window - now
        events.append(now)
        return None

    def _prune(self, now: float) -> None:
        """Forget keys without recent events, or the oldest keys if all are busy."""
        for key in [
            k for k, ev in self._events.items() if ev[-1] <= now - self._window
        ]:
            del self._events[key]
        while len(self._events) >= MAX_TRACKED_KEYS:
            del self._events[next(iter(self._events))]


class FailureLockout:
    """Lock a key out after too many failures within a window.

    Successes never reset the counter: otherwise an attacker could interleave a
    known-good code between guesses.
    """

    def __init__(self, max_failures: int, window: float, duration: float) -> None:
        """Initialize the lockout."""
        self._max_failures = max_failures
        self._window = window
        self._duration = duration
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}

    def locked_for(self, key: str, now: float) -> float | None:
        """Return the remaining lockout in seconds, or None if not locked."""
        until = self._locked_until.get(key)
        if until is None:
            return None
        if until <= now:
            del self._locked_until[key]
            return None
        return until - now

    def record_failure(self, key: str, now: float) -> bool:
        """Count a failure; return True if the key just got locked out."""
        failures = self._failures.setdefault(key, deque())
        while failures and failures[0] <= now - self._window:
            failures.popleft()
        failures.append(now)
        if len(failures) < self._max_failures:
            return False
        failures.clear()
        self._locked_until[key] = now + self._duration
        return True

    def locked_count(self, now: float) -> int:
        """Return how many keys are currently locked out."""
        return sum(1 for until in self._locked_until.values() if until > now)
