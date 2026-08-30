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


def _official(provider: str, mid: str) -> bool:
    """Heuristic for the provider's own (official) listing of a model: the
    model id starts with the provider id (``deepseek/deepseek-v4-pro``,
    ``openai/gpt-5``). Third-party aggregators list the same model under a
    longer, namespaced id (``openrouter/deepseek/deepseek-v4-pro``)."""
    return bool(provider) and mid.startswith(provider)


def _match_score(q: str, full_id: str, mid: str, name: str, provider: str, family: str) -> int:
    """Tiered relevance score — exact/whole-string matches and the provider's
    own (official) listing outrank prefixes, which outrank substrings, which
    outrank provider/family hits. 0 = no match.
    """
    if full_id == q:
        return 100
    if mid == q:
        # The official provider's own entry leads the pack.
        return 90 if _official(provider, mid) else 80
    if name == q:
        return 70
    if full_id.startswith(q):
        return 60
    if mid.startswith(q) or name.startswith(q):
        return 50
    if q in mid:
        return 40
    if q in name:
        return 30
    if provider and q in provider:
        return 20
    if family and q in family:
        return 10
    return 0


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

    A query can match the model id, its display name, the full ``provider/model``
    id, the provider id, or its ``family``. Whole-string matches beat prefixes,
    prefixes beat substrings, and a provider's own (official) listing of a model
    outranks third-party aggregates of the same model (so searching
    ``deepseek-v4-pro`` leads with ``deepseek/deepseek-v4-pro``). Ties prefer the
    shorter full id (official ids are the short ones), then alphabetical order.
    """
    q = (query or "").strip().lower()
    if not q:
        return []
    scored: list[tuple[int, int, str, dict]] = []
    for full_id, entry in iter_registry_models(rows):
        mid = str(entry.get("id") or "").lower()
        name = str(entry.get("name") or "").lower()
        provider = str(entry.get("provider") or "").lower()
        family = str(entry.get("family") or "").lower()
        s = _match_score(q, full_id.lower(), mid, name, provider, family)
        if s:
            scored.append((s, len(full_id), full_id.lower(), entry))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return [t[3] for t in scored[:limit]]


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
