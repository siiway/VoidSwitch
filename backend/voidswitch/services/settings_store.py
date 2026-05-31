"""Runtime settings store backed by the ``settings`` table with a small cache.

Operational thresholds (failure limits, probe intervals, timeouts) live here so
they can be tuned from the dashboard without a redeploy. Values are cached in
process and invalidated on write.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import DEFAULT_SETTINGS
from voidswitch.models.db import Setting

_cache: dict[str, Any] = {}
_cache_loaded = False
_lock = asyncio.Lock()


async def ensure_defaults(session: AsyncSession) -> None:
    """Seed any missing default settings rows (idempotent)."""
    existing_keys = {row[0] for row in (await session.execute(select(Setting.key))).all()}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing_keys:
            session.add(Setting(key=key, value=value))
    await session.flush()


async def load_all(session: AsyncSession) -> dict[str, Any]:
    """Load all settings (defaults overlaid with stored values) and refresh cache."""
    global _cache_loaded
    rows = (await session.execute(select(Setting))).scalars().all()
    merged: dict[str, Any] = dict(DEFAULT_SETTINGS)
    for row in rows:
        merged[row.key] = row.value
    async with _lock:
        _cache.clear()
        _cache.update(merged)
        _cache_loaded = True
    return merged


async def get_all(session: AsyncSession) -> dict[str, Any]:
    if not _cache_loaded:
        return await load_all(session)
    return dict(_cache)


def get_cached(key: str, default: Any = None) -> Any:
    """Synchronous cached read for hot paths (dispatcher). Falls back to defaults."""
    if key in _cache:
        return _cache[key]
    return DEFAULT_SETTINGS.get(key, default)


def get_int(key: str, default: int = 0) -> int:
    value = get_cached(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    value = get_cached(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def update(session: AsyncSession, values: dict[str, Any]) -> dict[str, Any]:
    """Upsert provided settings and refresh the cache."""
    for key, value in values.items():
        existing = await session.get(Setting, key)
        if existing is None:
            session.add(Setting(key=key, value=value))
        else:
            existing.value = value
    await session.flush()
    return await load_all(session)
