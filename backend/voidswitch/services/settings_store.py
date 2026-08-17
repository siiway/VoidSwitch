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


# Settings keys that were renamed. Maps old → new so a stored value survives the
# rename instead of silently reverting to the new key's default.
_RENAMED_KEYS: dict[str, str] = {
    # ``proxy_resurrector_enabled`` grew from "re-enable recovered proxies" into
    # a full proxy health-check master switch (probe + auto-disable + auto-enable).
    "proxy_resurrector_enabled": "proxy_health_check_enabled",
}


async def ensure_defaults(session: AsyncSession) -> None:
    """Seed any missing default settings rows (idempotent), migrating renames."""
    rows = {row.key: row for row in (await session.execute(select(Setting))).scalars().all()}
    # Carry a renamed key's stored value forward before seeding defaults, so an
    # operator's explicit choice is preserved across the rename.
    for old_key, new_key in _RENAMED_KEYS.items():
        if old_key in rows and new_key not in rows:
            session.add(Setting(key=new_key, value=rows[old_key].value))
            rows[new_key] = rows[old_key]  # mark present so the default isn't seeded
        # Delete the old-name row so it doesn't surface in load_all or the UI.
        if old_key in rows:
            await session.delete(rows[old_key])
    for key, value in DEFAULT_SETTINGS.items():
        if key not in rows:
            session.add(Setting(key=key, value=value))
    await session.flush()


async def load_all(session: AsyncSession) -> dict[str, Any]:
    """Load all settings (defaults overlaid with stored values) and refresh cache."""
    global _cache_loaded
    rows = (await session.execute(select(Setting))).scalars().all()
    merged: dict[str, Any] = dict(DEFAULT_SETTINGS)
    for row in rows:
        # Skip renamed keys so their old value doesn't leak into the returned dict
        # under the obsolete name (the current key was already migrated by
        # ensure_defaults and any new-name row already carries the value).
        if row.key in _RENAMED_KEYS:
            continue
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


def get_float(key: str, default: float = 0.0) -> float:
    value = get_cached(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    value = get_cached(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def get_str(key: str, default: str = "") -> str:
    value = get_cached(key, default)
    if isinstance(value, str):
        return value
    return str(value) if value is not None else default


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
