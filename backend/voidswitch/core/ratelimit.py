"""In-process, per-subject sliding-window rate limiting.

Single-node only (state lives in this process, like the gateway's RPM limiter).
Two shared limiters cover the two configurable abuse limits:

* :data:`operation_limiter` — mutating dashboard/management actions, keyed per
  signed-in user.
* :data:`call_limiter` — the OpenAI/Anthropic gateway endpoints, keyed per
  Void-Token owner.

Both are enforced for *everyone* (owners included); each subject is counted
independently. A ``max_requests`` of 0 (or a non-positive window) disables the
limiter.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """A per-key sliding-window counter. Not shared across processes."""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = defaultdict(deque)

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
        return True


# Process-wide singletons shared by the request guards.
operation_limiter = SlidingWindowLimiter()
call_limiter = SlidingWindowLimiter()
