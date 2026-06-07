"""Selection of providers, keys, and outbound routes for a request.

Selection favours healthy, least-recently-used resources so load spreads evenly
and recently-failed resources drift to the back of the queue.
"""

from __future__ import annotations

import datetime as dt
from fnmatch import fnmatch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus, ProxyMode, ProxyStatus
from voidswitch.models.db import ApiKey, Provider, Proxy
from voidswitch.services.network import Route

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


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


async def select_providers(session: AsyncSession, model: str) -> list[Provider]:
    """Enabled providers that serve ``model``, best-priority first."""
    rows = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    )
    matched = [p for p in rows if provider_serves_model(p, model)]
    matched.sort(key=lambda p: (p.priority, -p.weight, p.id))
    return matched


def select_keys(provider: Provider, pool: str = "") -> list[ApiKey]:
    """Active keys for a provider, weighted-least-used first.

    When ``pool`` is non-empty, only keys carrying that pool tag are used (so an
    alias route can target e.g. just the "leaked" or "members" keys). An empty
    pool uses every active key regardless of tag.
    """
    active = [k for k in provider.keys if k.status == KeyStatus.ACTIVE.value]
    if pool:
        active = [k for k in active if (k.pool or "") == pool]

    def sort_key(k: ApiKey) -> tuple[int, float, dt.datetime]:
        weight = max(k.weight, 1)
        return (k.failed_count, k.total_requests / weight, _lru_key(k.last_used_at))

    active.sort(key=sort_key)
    return active


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


async def select_routes(
    session: AsyncSession, provider: Provider | None = None
) -> list[tuple[Route, Proxy | None]]:
    """Ordered outbound routes. Honours ``provider.proxy_mode`` when given;
    otherwise uses the full active pool (direct fallback)."""
    proxies = await active_proxies(session)
    if provider is None:
        return _routes(proxies) if proxies else [(Route(), None)]
    return routes_for_provider(provider, proxies)
