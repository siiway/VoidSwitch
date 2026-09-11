"""Shared per-user concurrency guard for all server-sent event endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, status

from voidswitch.services import settings_store

_active: dict[str, int] = {}
_lock = asyncio.Lock()


async def acquire(user_sub: str, limit: int | None = None) -> None:
    if limit is None:
        limit = settings_store.get_int("sse_max_connections_per_user", 2)
    async with _lock:
        current = _active.get(user_sub, 0)
        if limit > 0 and current >= limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many concurrent SSE connections.",
            )
        _active[user_sub] = current + 1


async def release(user_sub: str) -> None:
    async with _lock:
        current = _active.get(user_sub, 0)
        if current <= 1:
            _active.pop(user_sub, None)
        else:
            _active[user_sub] = current - 1


@asynccontextmanager
async def slot(user_sub: str) -> AsyncIterator[None]:
    await acquire(user_sub)
    try:
        yield
    finally:
        await release(user_sub)


def clear() -> None:
    """Reset process-local counters (primarily for isolated test applications)."""
    _active.clear()
