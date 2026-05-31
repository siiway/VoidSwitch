"""Selection of providers, keys, and outbound routes for a request.

Selection favours healthy, least-recently-used resources so load spreads evenly
and recently-failed resources drift to the back of the queue.
"""

from __future__ import annotations

import datetime as dt
from fnmatch import fnmatch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus, ProxyStatus
from voidswitch.models.db import ApiKey, Provider, Proxy
from voidswitch.services.network import Route

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _lru_key(last_used: dt.datetime | None) -> dt.datetime:
    if last_used is None:
        return _EPOCH
    if last_used.tzinfo is None:
        return last_used.replace(tzinfo=dt.UTC)
    return last_used


def provider_serves_model(provider: Provider, model: str) -> bool:
    patterns = provider.models or []
    if not patterns:
        return False
    for pattern in patterns:
        if pattern == "*" or pattern == model or fnmatch(model, pattern):
            return True
    return False


async def select_providers(session: AsyncSession, model: str) -> list[Provider]:
    """Enabled providers that serve ``model``, best-priority first."""
    rows = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    )
    matched = [p for p in rows if provider_serves_model(p, model)]
    matched.sort(key=lambda p: (p.priority, -p.weight, p.id))
    return matched


def select_keys(provider: Provider) -> list[ApiKey]:
    """Active keys for a provider, weighted-least-used first."""
    active = [k for k in provider.keys if k.status == KeyStatus.ACTIVE.value]

    def sort_key(k: ApiKey) -> tuple[int, float, dt.datetime]:
        weight = max(k.weight, 1)
        return (k.failed_count, k.total_requests / weight, _lru_key(k.last_used_at))

    active.sort(key=sort_key)
    return active


async def select_routes(session: AsyncSession) -> list[tuple[Route, Proxy | None]]:
    """Ordered outbound routes. Uses active proxies; falls back to direct."""
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
    proxies = list(rows)
    if not proxies:
        return [(Route(), None)]
    proxies.sort(key=lambda p: (p.failed_count, _lru_key(p.last_used_at)))
    return [(Route(proxy_url=p.url or None, local_address=p.local_address), p) for p in proxies]
