"""Abuse rate limiting: the sliding-window limiter + the settings save-guard."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from voidswitch.api.admin.settings import _validate_operation_rate_limit
from voidswitch.core.config import get_settings
from voidswitch.core.ratelimit import SlidingWindowLimiter
from voidswitch.core.security import create_session_token

pytestmark = pytest.mark.asyncio


def _owner_headers() -> dict[str, str]:
    token = create_session_token(
        secret=get_settings().server.secret_key,
        subject="user-1",
        extra={"role": "owner", "name": "alice", "epoch": 0},
    )
    return {"Authorization": f"Bearer {token}"}


def test_sliding_window_disabled_allows_everything():
    lim = SlidingWindowLimiter()
    for _ in range(100):
        assert lim.allow("k", window_seconds=10, max_requests=0) is True


def test_sliding_window_enforces_max():
    lim = SlidingWindowLimiter()
    assert lim.allow("k", window_seconds=100, max_requests=2) is True
    assert lim.allow("k", window_seconds=100, max_requests=2) is True
    # Third within the window is blocked.
    assert lim.allow("k", window_seconds=100, max_requests=2) is False
    # A different key has its own budget.
    assert lim.allow("other", window_seconds=100, max_requests=2) is True


def test_validate_operation_rate_limit_guard():
    # Disabled → always fine.
    _validate_operation_rate_limit({"operation_rate_limit_max_requests": 0})
    # Comfortably above the floor → fine (20 per 10s = 120/min).
    _validate_operation_rate_limit(
        {
            "operation_rate_limit_window_seconds": 10,
            "operation_rate_limit_max_requests": 20,
        }
    )
    # Too low (1 per 60s) → rejected to avoid a lockout.
    with pytest.raises(HTTPException):
        _validate_operation_rate_limit(
            {
                "operation_rate_limit_window_seconds": 60,
                "operation_rate_limit_max_requests": 1,
            }
        )


async def test_settings_put_rejects_too_low_operation_limit(client, seeded):
    resp = await client.put(
        "/api/admin/settings",
        headers=_owner_headers(),
        json={
            "values": {
                "operation_rate_limit_window_seconds": 3600,
                "operation_rate_limit_max_requests": 1,
            }
        },
    )
    assert resp.status_code == 400
