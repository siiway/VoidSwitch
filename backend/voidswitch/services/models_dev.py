"""models.dev registry integration.

The registry is the public OpenCode model catalog served from
``https://models.dev/api.json`` (a JSON object mapping model id → entry). The
dashboard can match an exposed model to a registry id; the matched entry is used
as *placeholder* metadata (only ever a fallback — explicitly filled fields and
custom ``opencode_config`` override it). Rows are cached locally so the sync is
a single background pull and search never hits the network.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.logging import get_logger
from voidswitch.models.db import ModelsDevCache
from voidswitch.services import settings_store

log = get_logger("models_dev")

_REGISTRY_URL = "https://models.dev/api.json"
_FETCH_TIMEOUT = 20.0


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def sync_interval_minutes() -> int:
    return max(0, settings_store.get_int("models_dev_sync_interval_minutes", 1440))


def sync_enabled() -> bool:
    return sync_interval_minutes() > 0


async def fetch_registry() -> dict[str, dict]:
    """Fetch the raw models.dev registry (outside the routing system — this is
    a plain public catalog pull; failures are logged and return empty)."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=_FETCH_TIMEOUT, write=10.0, pool=10.0)
        ) as client:
            resp = await client.get(_REGISTRY_URL, follow_redirects=True)
            if resp.status_code != 200:
                log.warning("models_dev_fetch_status", status=resp.status_code)
                return {}
            data = resp.json()
    except Exception as exc:  # pragma: no cover - network path
        log.warning("models_dev_fetch_failed", error=f"{type(exc).__name__}: {exc}")
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


async def sync_now(session: AsyncSession) -> int:
    """Pull the registry and upsert the local cache. Returns entry count."""
    registry = await fetch_registry()
    if not registry:
        return 0
    now = _now()
    existing = {
        row.id: row for row in (await session.execute(select(ModelsDevCache))).scalars().all()
    }
    for mid, entry in registry.items():
        row = existing.get(mid)
        if row is None:
            session.add(ModelsDevCache(id=mid, data=entry, updated_at=now))
        else:
            row.data = entry
            row.updated_at = now
    await session.flush()
    return len(registry)


async def get_model(session: AsyncSession, model_id: str | None) -> dict | None:
    if not model_id:
        return None
    row = (
        await session.execute(select(ModelsDevCache).where(ModelsDevCache.id == model_id))
    ).scalar_one_or_none()
    return row.data if row is not None else None


def _score(q: str, mid: str, name: str) -> int:
    """A tiny relevance score: exact prefix first, then substring, else 0."""
    q = q.lower()
    mid_l, name_l = mid.lower(), name.lower()
    if mid_l == q or name_l == q:
        return 3
    if mid_l.startswith(q) or name_l.startswith(q):
        return 2
    if q in mid_l or q in name_l:
        return 1
    return 0


def search_cached(rows: Sequence[ModelsDevCache], query: str, limit: int = 50) -> list[dict]:
    """Local relevance search over cached registry entries."""
    q = (query or "").strip()
    if not q:
        return []
    scored: list[tuple[int, str, dict]] = []
    for row in rows:
        name = str((row.data or {}).get("name") or row.id)
        s = _score(q, row.id, name)
        if s:
            scored.append((s, row.id, row.data))
    scored.sort(key=lambda t: (-t[0], t[1].lower()))
    return [t[2] for t in scored[:limit]]


def iter_registry_models(rows: Sequence[ModelsDevCache]) -> list[tuple[str, dict]]:
    """Flatten cached provider entries into ``(full_id, model_entry)`` pairs.

    The registry maps a provider id → a provider object whose ``models`` dict
    holds the individual model entries. ``full_id`` is ``provider/model`` (the
    stable id used as ``models_dev_id``); each model entry is augmented with its
    provider id/name so the dashboard can derive a brand for the icon.
    """
    out: list[tuple[str, dict]] = []
    for row in rows:
        provider = row.data or {}
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        provider_name = str(provider.get("name") or row.id)
        for mid, model in models.items():
            if not isinstance(model, dict):
                continue
            entry = dict(model)
            entry.setdefault("id", mid)
            entry["provider"] = row.id
            entry["provider_name"] = provider_name
            out.append((f"{row.id}/{mid}", entry))
    return out


def search_models(rows: Sequence[ModelsDevCache], query: str, limit: int = 100) -> list[dict]:
    """Relevance search over the flattened *model* entries (not providers).

    A query can match the model id, its display name, the provider id/name, or
    its ``family``. Returns the flattened model entries.
    """
    q = (query or "").strip()
    if not q:
        return []
    ql = q.lower()
    scored: list[tuple[int, str, dict]] = []
    for full_id, entry in iter_registry_models(rows):
        mid = str(entry.get("id") or "").lower()
        name = str(entry.get("name") or "").lower()
        provider = str(entry.get("provider") or "").lower()
        family = str(entry.get("family") or "").lower()
        if ql in (mid, name, full_id.lower()):
            s = 3
        elif mid.startswith(ql) or name.startswith(ql) or full_id.lower().startswith(ql):
            s = 2
        elif ql in mid or ql in name or ql in provider or ql in family:
            s = 1
        else:
            continue
        scored.append((s, full_id, entry))
    scored.sort(key=lambda t: (-t[0], t[1].lower()))
    return [t[2] for t in scored[:limit]]


def resolve_model(rows: Sequence[ModelsDevCache], full_id: str) -> dict | None:
    """Resolve a ``provider/model`` id back to its flattened model entry."""
    provider_id, _, mid = full_id.partition("/")
    if not provider_id or not mid:
        return None
    for row in rows:
        if row.id != provider_id:
            continue
        models = (row.data or {}).get("models")
        if isinstance(models, dict) and mid in models and isinstance(models[mid], dict):
            return dict(models[mid])
    return None
