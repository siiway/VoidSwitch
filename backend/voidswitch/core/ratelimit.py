"""In-process, per-subject sliding-window rate limiting.

.. important::
   **Single-node only.** All counters live in this process. Run VoidSwitch as a
   single uvicorn worker (the default; see ``voidswitch/__main__.py``). Under
   multiple workers each process keeps its own counters, so every limiter here —
   and the per-token RPM guard that shares :data:`gateway_rpm_limiter` — becomes
   *per-worker* and the effective limit is multiplied by the worker count. A
   cross-process limit needs a shared backend (e.g. Redis); that is intentionally
   out of scope for the single-node deployment this project targets.

Three shared limiters cover the configurable abuse/quota limits:

* :data:`operation_limiter` — mutating dashboard/management actions, keyed per
  signed-in user, with a fixed window/max (see
  ``constants.OPERATION_RATE_LIMIT_*``).
* :data:`call_limiter` — the OpenAI/Anthropic gateway endpoints, keyed per
  (user, role group); each role group carries its own window/max and a member
  of several groups passes as long as any of them has budget left.
* :data:`gateway_rpm_limiter` — the per-Void-Token ``rpm_limit`` on the gateway.

All are enforced for *everyone* (owners included); each subject is counted
independently. A ``max_requests`` of 0 (or a non-positive window) disables the
limiter.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """A per-key sliding-window counter. Not shared across processes."""

    # Sweep frequency for dropping long-idle subjects (bounds memory on the
    # otherwise-unbounded subject table).
    _GC_INTERVAL = 60.0

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._last_gc = time.monotonic()

    def allow(self, key: str, *, window_seconds: float, max_requests: int) -> bool:
        """Record a hit for ``key`` and return whether it is within the limit.

        Returns ``True`` (and counts the hit) when allowed, ``False`` when the
        window is already full. Disabled (``max_requests <= 0`` or
        ``window_seconds <= 0``) always allows and records nothing.
        """
        if max_requests <= 0 or window_seconds <= 0:
            return True
        now = time.monotonic()
        window = self._windows[key]
        cutoff = now - window_seconds
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= max_requests:
            return False
        window.append(now)
        self._maybe_gc(now, window_seconds)
        return True

    def remaining(self, key: str, *, window_seconds: float, max_requests: int) -> int:
        """Capacity left for ``key`` without recording a hit (peek).

        Returns ``max_requests`` when the limiter is disabled for these
        parameters (``max_requests <= 0`` or ``window_seconds <= 0``), so a
        disabled group always looks like it has budget.
        """
        if max_requests <= 0 or window_seconds <= 0:
            return max_requests if max_requests > 0 else 1
        now = time.monotonic()
        window = self._windows.get(key)
        if not window:
            return max_requests
        cutoff = now - window_seconds
        hits = sum(1 for ts in window if ts >= cutoff)
        return max(0, max_requests - hits)

    def _maybe_gc(self, now: float, window_seconds: float) -> None:
        """Drop subjects whose window is empty and last touched long ago.

        Without this, every distinct subject ever seen (every user, every token)
        keeps one dict entry for the process lifetime.
        """
        if now - self._last_gc < self._GC_INTERVAL:
            return
        self._last_gc = now
        cutoff = now - max(window_seconds * 2, 300.0)
        stale = [k for k, v in self._windows.items() if not v or v[-1] < cutoff]
        for k in stale:
            if not self._windows[k]:
                del self._windows[k]

    def clear(self) -> None:
        """Drop all recorded hits (used by the test-suite between tests)."""
        self._windows.clear()


# Process-wide singletons shared by the request guards.
operation_limiter = SlidingWindowLimiter()
call_limiter = SlidingWindowLimiter()
# Per-Void-Token RPM guard on the public gateway (60s sliding window).
gateway_rpm_limiter = SlidingWindowLimiter()
