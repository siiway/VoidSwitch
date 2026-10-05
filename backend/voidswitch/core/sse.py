"""Redis-backed per-user concurrency guard for SSE endpoints."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import HTTPException, status

from voidswitch.core.redis import RedisService, get_redis
from voidswitch.services import settings_store

_LEASE_SECONDS = 90
_renewals: dict[str, tuple[str, asyncio.Task[None]]] = {}
_ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if tonumber(ARGV[1]) > 0 and redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[2]), ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) + 1000)
return 1
"""
_RENEW_SCRIPT = """
local score = redis.call('ZSCORE', KEYS[1], ARGV[2])
if not score then return 0 end
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[1]), ARGV[2])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]) + 1000)
return 1
"""


async def acquire(user_sub: str, limit: int | None = None) -> str:
    if limit is None:
        limit = settings_store.get_int("sse_max_connections_per_user", 2)
    redis = get_redis()
    lease_id = uuid4().hex
    acquired = await redis.client.eval(
        _ACQUIRE_SCRIPT,
        1,
        redis.key("sse", user_sub),
        limit,
        _LEASE_SECONDS * 1000,
        lease_id,
    )
    if not acquired:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many concurrent SSE connections."
        )
    _renewals[lease_id] = (
        user_sub,
        asyncio.create_task(_renew(redis, user_sub, lease_id), name=f"redis:sse:{user_sub}"),
    )
    return lease_id


async def release(user_sub: str, lease_id: str | None = None) -> None:
    redis = get_redis()
    key = redis.key("sse", user_sub)
    if lease_id is None:
        return
    else:
        entry = _renewals.pop(lease_id, None)
        if entry is not None:
            _, renewal = entry
            renewal.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await renewal
        await redis.client.zrem(key, lease_id)


async def _renew(redis: RedisService, user_sub: str, lease_id: str) -> None:
    ttl_ms = _LEASE_SECONDS * 1000
    while True:
        await asyncio.sleep(_LEASE_SECONDS / 3)
        try:
            renewed = await redis.client.eval(
                _RENEW_SCRIPT, 1, redis.key("sse", user_sub), ttl_ms, lease_id
            )
        except Exception:
            _renewals.pop(lease_id, None)
            return
        if not renewed:
            _renewals.pop(lease_id, None)
            return


@asynccontextmanager
async def slot(user_sub: str) -> AsyncIterator[None]:
    lease_id = await acquire(user_sub)
    try:
        yield
    finally:
        await release(user_sub, lease_id)


def clear() -> None:
    """Compatibility no-op; tests use isolated Redis namespaces."""
