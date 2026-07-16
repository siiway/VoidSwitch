"""Selection of providers, keys, and outbound routes for a request.

Selection favours healthy, least-recently-used resources so load spreads evenly
and recently-failed resources drift to the back of the queue.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import time
from dataclasses import dataclass
from fnmatch import fnmatch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeySelectMode, KeyStatus, ProxyMode, ProxyStatus
from voidswitch.models.db import ApiKey, Provider, Proxy
from voidswitch.services.network import Route

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --------------------------------------------------------------------------- #
# In-process key-selection state (round-robin cursors + per-session pins)
# --------------------------------------------------------------------------- #
#
# These are intentionally process-local: like the gateway's RPM limiter they
# trade perfect cross-worker coordination for zero shared-state overhead. A
# round-robin cursor that drifts slightly between workers, or a session that
# re-pins after a worker restart, is harmless — every mode still falls back
# through the full key list on the dispatch path.

# (provider_id, pool) -> monotonically increasing request counter.
_rr_cursors: dict[tuple[int, str], int] = {}

# (provider_id, pool, session_key) -> (pinned key id, last-seen monotonic time).
_pins: dict[tuple[int, str, str], tuple[int, float]] = {}

# How long a session pin survives without traffic before it is purged.
_PIN_TTL_SECONDS = 3600.0
# Purge sweeps only run once the pin table grows past this many entries.
_PIN_PURGE_THRESHOLD = 4096


def _next_cursor(provider_id: int, pool: str) -> int:
    key = (provider_id, pool)
    value = _rr_cursors.get(key, 0)
    _rr_cursors[key] = value + 1
    return value


def _purge_pins(now: float) -> None:
    if len(_pins) <= _PIN_PURGE_THRESHOLD:
        return
    stale = [k for k, (_, seen) in _pins.items() if now - seen > _PIN_TTL_SECONDS]
    for k in stale:
        del _pins[k]


def _lookup_pin(provider_id: int, pool: str, session_key: str, valid_ids: set[int]) -> int | None:
    """Return the live pinned key id for a session, or None if absent/stale/dead."""
    entry = _pins.get((provider_id, pool, session_key))
    if entry is None:
        return None
    key_id, seen = entry
    now = time.monotonic()
    if now - seen > _PIN_TTL_SECONDS or key_id not in valid_ids:
        _pins.pop((provider_id, pool, session_key), None)
        return None
    # Refresh the idle timer on every hit.
    _pins[(provider_id, pool, session_key)] = (key_id, now)
    return key_id


def _store_pin(provider_id: int, pool: str, session_key: str, key_id: int) -> None:
    now = time.monotonic()
    _purge_pins(now)
    _pins[(provider_id, pool, session_key)] = (key_id, now)


def reset_selection_state() -> None:
    """Clear all round-robin cursors, session pins, and the provider index (tests)."""
    global _index_signature, _index_cache
    _rr_cursors.clear()
    _pins.clear()
    _index_signature = None
    _index_cache = None



def _lru_key(last_used: dt.datetime | None) -> dt.datetime:
    if last_used is None:
        return _EPOCH
    if last_used.tzinfo is None:
        return last_used.replace(tzinfo=dt.UTC)
    return last_used


def match_model_route(provider: Provider, model: str) -> dict | None:
    """The provider's alias route whose ``alias`` exactly equals ``model``, if any."""
    for route in provider.model_routes or []:
        if isinstance(route, dict) and route.get("alias") == model:
            return route
    return None


def routed_upstreams(provider: Provider) -> set[str]:
    """Upstream model ids that are only reachable through one of this provider's
    alias routes.

    When a route maps ``deepseek-v4-flash-lkd`` → upstream ``deepseek-v4-flash``,
    the raw ``deepseek-v4-flash`` is considered "behind" the route: it is no
    longer advertised or callable under its own name — only via the alias(es).
    A model id that is *also* a route alias on the same provider stays callable
    (the alias check in :func:`provider_serves_model` wins).
    """
    ups: set[str] = set()
    for route in provider.model_routes or []:
        if isinstance(route, dict):
            upstream = route.get("upstream")
            if isinstance(upstream, str) and upstream:
                ups.add(upstream)
    return ups


def provider_serves_model(provider: Provider, model: str) -> bool:
    # An exact model-route alias always counts (even if not in `models`).
    if match_model_route(provider, model) is not None:
        return True
    # A raw upstream that's been put behind an alias route is no longer callable
    # under its own id — only through the alias.
    if model in routed_upstreams(provider):
        return False
    patterns = provider.models or []
    if not patterns:
        return False
    for pattern in patterns:
        if pattern == "*" or pattern == model or fnmatch(model, pattern):
            return True
    return False


def resolve_model(provider: Provider, model: str) -> tuple[str, str]:
    """Resolve an inbound model to ``(upstream_model, key_pool)``.

    A matching alias route wins (its ``upstream`` / ``pool``); otherwise the
    upstream comes from ``model_map`` and the pool is empty (any key).
    """
    route = match_model_route(provider, model)
    if route is not None:
        upstream = route.get("upstream") or model
        return upstream, route.get("pool", "") or ""
    if provider.model_map:
        return provider.model_map.get(model, model), ""
    return model, ""


# --------------------------------------------------------------------------- #
# Provider→model index cache
# --------------------------------------------------------------------------- #
#
# Resolving which providers serve an inbound model used to load *every* enabled
# provider (plus their whole key list) on every request and filter in Python.
# Instead we keep a process-local index built from a metadata-only query and
# refresh it only when the provider set actually changes.
#
# The cache is keyed off a cheap signature — (count, max(updated_at)) over the
# enabled providers. Any insert/enable-toggle/edit bumps max(updated_at) (the
# TimestampMixin sets it on every write) and a delete changes the count, so the
# signature is guaranteed to move whenever a relevant row does. The signature
# query and the (rare) rebuild query never touch the key tables.

# Characters that make a `models` pattern a glob rather than a literal.
_GLOB_CHARS = ("*", "?", "[")


def _is_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in _GLOB_CHARS)


@dataclass(frozen=True)
class _ProviderMeta:
    id: int
    priority: int
    weight: int
    route_aliases: frozenset[str]
    routed_upstreams: frozenset[str]
    literal_models: frozenset[str]
    wildcards: tuple[str, ...]


def _meta_serves(meta: _ProviderMeta, model: str) -> bool:
    """Mirror of :func:`provider_serves_model` operating on precomputed metadata."""
    if model in meta.route_aliases:
        return True
    if model in meta.routed_upstreams:
        return False
    if model in meta.literal_models:
        return True
    return any(pattern == "*" or fnmatch(model, pattern) for pattern in meta.wildcards)


@dataclass(frozen=True)
class _ProviderIndex:
    metas: dict[int, _ProviderMeta]
    # Inbound model → provider ids that serve it via an exact alias/literal.
    exact: dict[str, list[int]]
    # Providers carrying at least one glob pattern (fallback scan).
    wildcard_ids: tuple[int, ...]

    def candidate_ids(self, model: str) -> list[int]:
        ids = list(self.exact.get(model, ()))
        seen = set(ids)
        for pid in self.wildcard_ids:
            if pid in seen:
                continue
            meta = self.metas.get(pid)
            if meta is not None and _meta_serves(meta, model):
                ids.append(pid)
                seen.add(pid)
        if not ids:
            return []
        ids.sort(key=lambda pid: (self.metas[pid].priority, -self.metas[pid].weight, pid))
        return ids


# (count, max_updated_at_iso) signature of the enabled provider set, and the
# index built for it. Both cleared by reset_selection_state().
_index_signature: tuple[int, str] | None = None
_index_cache: _ProviderIndex | None = None


def _meta_from_row(
    pid: int,
    priority: int,
    weight: int,
    models: list | None,
    model_routes: list | None,
) -> _ProviderMeta:
    route_aliases: set[str] = set()
    routed_ups: set[str] = set()
    for route in model_routes or []:
        if not isinstance(route, dict):
            continue
        alias = route.get("alias")
        if isinstance(alias, str) and alias:
            route_aliases.add(alias)
        upstream = route.get("upstream")
        if isinstance(upstream, str) and upstream:
            routed_ups.add(upstream)
    literal: set[str] = set()
    wildcards: list[str] = []
    for pattern in models or []:
        if not isinstance(pattern, str):
            continue
        if _is_glob(pattern):
            wildcards.append(pattern)
        else:
            literal.add(pattern)
    return _ProviderMeta(
        id=pid,
        priority=priority,
        weight=weight,
        route_aliases=frozenset(route_aliases),
        routed_upstreams=frozenset(routed_ups),
        literal_models=frozenset(literal),
        wildcards=tuple(wildcards),
    )


def _build_index(rows) -> _ProviderIndex:
    metas: dict[int, _ProviderMeta] = {}
    exact: dict[str, list[int]] = {}
    wildcard_ids: list[int] = []
    for pid, priority, weight, models, model_routes in rows:
        meta = _meta_from_row(pid, priority, weight, models, model_routes)
        metas[pid] = meta
        # Exact matches: every route alias, plus literal models the provider
        # actually serves (a literal can be shadowed by a routed upstream).
        exact_models = set(meta.route_aliases)
        for m in meta.literal_models:
            if _meta_serves(meta, m):
                exact_models.add(m)
        for m in exact_models:
            exact.setdefault(m, []).append(pid)
        if meta.wildcards:
            wildcard_ids.append(pid)
    return _ProviderIndex(metas=metas, exact=exact, wildcard_ids=tuple(wildcard_ids))


async def _provider_signature(session: AsyncSession) -> tuple[int, str]:
    row = (
        await session.execute(
            select(func.count(Provider.id), func.max(Provider.updated_at)).where(
                Provider.enabled.is_(True)
            )
        )
    ).one()
    count = int(row[0] or 0)
    max_updated = row[1]
    return count, (max_updated.isoformat() if max_updated is not None else "")


async def _get_index(session: AsyncSession) -> _ProviderIndex:
    global _index_signature, _index_cache
    signature = await _provider_signature(session)
    if _index_cache is None or signature != _index_signature:
        rows = (
            await session.execute(
                select(
                    Provider.id,
                    Provider.priority,
                    Provider.weight,
                    Provider.models,
                    Provider.model_routes,
                ).where(Provider.enabled.is_(True))
            )
        ).all()
        _index_cache = _build_index(rows)
        _index_signature = signature
    return _index_cache


async def select_providers(session: AsyncSession, model: str) -> list[Provider]:
    """Enabled providers that serve ``model``, best-priority first."""
    index = await _get_index(session)
    ordered_ids = index.candidate_ids(model)
    if not ordered_ids:
        return []
    rows = (
        (await session.execute(select(Provider).where(Provider.id.in_(ordered_ids))))
        .scalars()
        .all()
    )
    by_id = {p.id: p for p in rows}
    return [by_id[pid] for pid in ordered_ids if pid in by_id]


def _manual_order(candidates: list[ApiKey]) -> list[ApiKey]:
    """Candidates in the operator's drag-sorted order (lowest ``sort_order`` first)."""
    return sorted(candidates, key=lambda k: (k.sort_order or 0, k.id or 0))


def _rotate(ordered: list[ApiKey], provider_id: int, pool: str) -> list[ApiKey]:
    """Manual order rotated so a different key leads each request (round-robin)."""
    if len(ordered) <= 1:
        return ordered
    start = _next_cursor(provider_id, pool) % len(ordered)
    return ordered[start:] + ordered[:start]


def _lead_with(ordered: list[ApiKey], key_id: int) -> list[ApiKey]:
    """Move the key with ``key_id`` to the front, keeping the rest in order."""
    lead = [k for k in ordered if k.id == key_id]
    rest = [k for k in ordered if k.id != key_id]
    return lead + rest


def _apply_mode(
    provider: Provider,
    candidates: list[ApiKey],
    *,
    pool: str,
    session_key: str | None,
) -> list[ApiKey]:
    """Apply the provider's key-select mode to a single candidate list.

    The returned list is a try order; the dispatcher walks it from the front and
    falls back through the remainder on any failure, so "unless the key is
    unavailable" is handled for free for every mode.
    """
    if len(candidates) <= 1:
        return candidates

    mode = provider.key_select_mode or KeySelectMode.ROUND_ROBIN.value
    provider_id = provider.id or 0
    manual = _manual_order(candidates)

    if mode == KeySelectMode.FALLBACK.value:
        return manual
    if mode == KeySelectMode.RANDOM.value:
        shuffled = list(manual)
        random.shuffle(shuffled)
        return shuffled
    if mode == KeySelectMode.ROUND_ROBIN.value:
        return _rotate(manual, provider_id, pool)

    pinned = mode in (
        KeySelectMode.PINNED_ROUND_ROBIN.value,
        KeySelectMode.PINNED_RANDOM.value,
    )
    if pinned:
        valid_ids = {k.id for k in manual if k.id is not None}
        # Reuse a live pin when this session already has one.
        if session_key is not None:
            existing = _lookup_pin(provider_id, pool, session_key, valid_ids)
            if existing is not None:
                return _lead_with(manual, existing)
        # Assign a fresh pin via the mode's sub-strategy.
        if mode == KeySelectMode.PINNED_RANDOM.value:
            chosen = random.choice(manual)
        else:  # pinned round-robin
            chosen = _rotate(manual, provider_id, pool)[0]
        if session_key is not None and chosen.id is not None:
            _store_pin(provider_id, pool, session_key, chosen.id)
        return _lead_with(manual, chosen.id) if chosen.id is not None else manual

    # Unknown / legacy mode → round-robin.
    return _rotate(manual, provider_id, pool)


def _ordered_candidates(
    provider: Provider,
    active: list[ApiKey],
    recovered: list[ApiKey],
    *,
    pool: str,
    session_key: str | None,
) -> list[ApiKey]:
    """Full per-request try order: healthy keys first, recovered ones last.

    Active keys are ordered by the provider's key-select mode. Keys that recovered
    from a rate limit are *always* appended after them — they are a last resort,
    so a request burns through every healthy key before re-touching one that was
    recently 429'd (this is what keeps a pile of rate-limited keys from exhausting
    the retry budget ahead of the few good ones). Recovered keys are themselves
    ordered by who has been free longest.
    """
    ordered = _apply_mode(provider, active, pool=pool, session_key=session_key)
    if recovered:
        recovered = sorted(
            recovered,
            key=lambda k: (_lru_key(k.rate_limit_until), k.sort_order or 0, k.id or 0),
        )
        ordered = ordered + recovered
    return ordered


def _rate_limited_eligible(k: ApiKey, now: dt.datetime, recovery_seconds: int) -> bool:
    """Whether a rate-limited key may re-enter the pool now.

    Prefers the per-key ``rate_limit_until`` (set from ``Retry-After`` / the
    provider cooldown). Falls back to the legacy ``disabled_since +
    rate_limit_recovery_seconds`` window for rows parked before this field existed.
    """
    if k.status != KeyStatus.RATE_LIMITED.value:
        return False
    until = k.rate_limit_until
    if until is not None:
        if until.tzinfo is None:
            until = until.replace(tzinfo=dt.UTC)
        return now >= until
    if recovery_seconds <= 0 or k.disabled_since is None:
        return False
    disabled_since = k.disabled_since
    if disabled_since.tzinfo is None:
        disabled_since = disabled_since.replace(tzinfo=dt.UTC)
    return (now - disabled_since).total_seconds() >= recovery_seconds


def select_keys(
    provider: Provider,
    pool: str = "",
    rate_limit_recovery_seconds: int = 0,
    *,
    session_key: str | None = None,
) -> list[ApiKey]:
    """Per-request key try order for a provider, honouring its key-select mode.

    When ``pool`` is non-empty, only keys carrying that pool tag are used (so an
    alias route can target e.g. just the "leaked" or "members" keys). An empty
    pool uses every active key regardless of tag.

    A rate-limited key is **excluded from the pool entirely** until its cooldown
    elapses (``rate_limit_until``, set from the upstream ``Retry-After`` header or
    the provider/global cooldown; ``rate_limit_recovery_seconds`` is the legacy
    fallback for rows parked before that field existed). Once eligible again it is
    ranked *after* every active key, so healthy keys are always tried first.

    The active set is ordered by ``provider.key_select_mode`` — round-robin,
    random, fallback, or one of the per-session pinned variants (``session_key``
    identifies the session).
    """
    now = _utcnow()
    active: list[ApiKey] = []
    recovered: list[ApiKey] = []
    for k in provider.keys:
        if k.status == KeyStatus.ACTIVE.value:
            active.append(k)
        elif _rate_limited_eligible(k, now, rate_limit_recovery_seconds):
            recovered.append(k)
    if pool:
        active = [k for k in active if (k.pool or "") == pool]
        recovered = [k for k in recovered if (k.pool or "") == pool]

    return _ordered_candidates(
        provider, active, recovered, pool=pool, session_key=session_key
    )


async def active_proxies(session: AsyncSession) -> list[Proxy]:
    """All enabled+active proxies (the global pool), unsorted."""
    rows = (
        (
            await session.execute(
                select(Proxy).where(
                    Proxy.enabled.is_(True),
                    Proxy.status == ProxyStatus.ACTIVE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


def _routes(proxies: list[Proxy]) -> list[tuple[Route, Proxy | None]]:
    ordered = sorted(proxies, key=lambda p: (p.failed_count, _lru_key(p.last_used_at)))
    return [(Route(proxy_url=p.url or None, local_address=p.local_address), p) for p in ordered]


def routes_for_provider(
    provider: Provider, proxies: list[Proxy]
) -> list[tuple[Route, Proxy | None]]:
    """Ordered outbound routes for one provider, honouring its proxy_mode.

    * ``direct``   → always [direct], never a proxy.
    * ``selected`` → only the assigned (and still-active) proxies, in best-first
      order; NO direct fallback (so a provider pinned to proxies never leaks the
      real IP). An empty result means the caller should skip this provider.
    * ``all`` (default) → the whole active pool, best-first; direct only if the
      pool is empty.
    """
    mode = provider.proxy_mode or ProxyMode.ALL.value
    if mode == ProxyMode.DIRECT.value:
        return [(Route(), None)]
    if mode == ProxyMode.SELECTED.value:
        ids = set(provider.proxy_ids or [])
        return _routes([p for p in proxies if p.id in ids])
    if not proxies:
        return [(Route(), None)]
    return _routes(proxies)


# Process HTTP(S) proxy env vars consulted (in order) when proxy switching is
# off and no explicit static proxy URL is configured.
_ENV_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)


def _env_proxy_url() -> str | None:
    for var in _ENV_PROXY_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()
    return None


def static_routes(static_proxy_url: str) -> list[tuple[Route, Proxy | None]]:
    """The single fixed outbound route used when proxy switching is disabled.

    Uses ``static_proxy_url`` when set; otherwise falls back to the process
    HTTP(S)_PROXY/ALL_PROXY env vars, and finally a direct connection. The
    ``Proxy`` element is always ``None`` so the dispatcher never disables a DB
    proxy row on failure (there is nothing to rotate to).
    """
    url = (static_proxy_url or "").strip() or _env_proxy_url()
    return [(Route(proxy_url=url or None), None)]


async def select_routes(
    session: AsyncSession, provider: Provider | None = None
) -> list[tuple[Route, Proxy | None]]:
    """Ordered outbound routes. Honours ``provider.proxy_mode`` when given;
    otherwise uses the full active pool (direct fallback)."""
    proxies = await active_proxies(session)
    if provider is None:
        return _routes(proxies) if proxies else [(Route(), None)]
    return routes_for_provider(provider, proxies)
