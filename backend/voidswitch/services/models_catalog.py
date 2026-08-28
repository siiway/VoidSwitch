"""Exposed model catalog.

The public catalog is the set of :class:`ExposedModel` rows — the only ids
clients ever see. Upstream ids (``slug/model``) are internal: they appear only
as route-pool refs and are never advertised. This module lists exposed models,
derives the set of currently-served upstream ids from providers (for the
"expose everything 1:1" sync), and cleans up exposed models with no reachable
upstream.
"""

from __future__ import annotations

from fnmatch import fnmatch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.models.db import ExposedModel, Provider, RouteLayer, RoutePoolEntry
from voidswitch.services import model_routing

_glob_chars = ("*", "?", "[")


def _is_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in _glob_chars)


def served_upstream_ids(providers: list[Provider]) -> set[str]:
    """Upstream model ids currently served by the providers (explicit names only).

    Wildcards match anything but name nothing, so they're excluded here — a
    globbed provider contributes no concrete upstream id to the catalog.
    """
    ids: set[str] = set()
    for provider in providers:
        for name in provider.models or []:
            if isinstance(name, str) and name and not _is_glob(name):
                ids.add(name)
    return ids


def providers_serving(providers: list[Provider], model_id: str) -> list[str]:
    """Names of providers whose ``models`` list matches ``model_id``."""
    return [
        p.name
        for p in providers
        if any(
            pattern == "*" or pattern == model_id or fnmatch(model_id, pattern)
            for pattern in (p.models or [])
        )
    ]


async def _enabled_providers(session: AsyncSession) -> list[Provider]:
    rows = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    )
    return list(rows)


async def upstream_refs(session: AsyncSession, exposed: ExposedModel) -> list[str]:
    """Human-facing ``slug/model`` strings reachable through a model's route."""
    route = exposed.route
    if route is None:
        return []
    refs: list[str] = []
    seen: set[tuple[int | None, str]] = set()
    for layer in route.layers:
        for entry in layer.entries:
            key = (entry.provider_id, entry.upstream_model)
            if key in seen:
                continue
            seen.add(key)
            provider = entry.provider
            if provider is None:
                continue
            slug = provider.slug or provider.name
            refs.append(f"{slug}/{entry.upstream_model}" if entry.upstream_model else slug)
    return refs


async def build_catalog(session: AsyncSession) -> list[ExposedModel]:
    """Every exposed model, ordered stably (by public id)."""
    rows = (await session.execute(select(ExposedModel))).scalars().all()
    return sorted(rows, key=lambda m: (m.model_id or "").lower())


async def sync_from_providers(
    session: AsyncSession, *, added_by: int | None = None, added_by_name: str | None = None
) -> tuple[int, int]:
    """Auto-expose every currently-served upstream id with a 1:1 passthrough route.

    For each served upstream id without an exposed model, create an exposed model
    and a default route: one layer, one pool entry per serving provider
    (weighted by the provider's priority/weight), upstream_model = the id. This
    preserves the old "catalog = union of provider models" behaviour as a
    starting point; operators then reshape the routes as they like.
    Returns ``(added, total)``.
    """
    providers = await _enabled_providers(session)
    existing = set((await session.execute(select(ExposedModel.model_id))).scalars().all())
    served = served_upstream_ids(providers)
    missing = sorted(served - existing)
    for model_id in missing:
        entry = ExposedModel(model_id=model_id, added_by=added_by, added_by_name=added_by_name)
        session.add(entry)
        await session.flush()
        route = await model_routing.get_or_create_route(session, entry)
        layer = RouteLayer(route_id=route.id, position=0, max_attempts=1)
        session.add(layer)
        await session.flush()
        for provider in providers:
            if not any(
                pattern == "*" or pattern == model_id or fnmatch(model_id, pattern)
                for pattern in (provider.models or [])
            ):
                continue
            session.add(
                RoutePoolEntry(
                    layer_id=layer.id,
                    provider_id=provider.id,
                    upstream_model=model_id,
                    weight=1,
                )
            )
    await session.flush()
    return len(missing), len(existing) + len(missing)


async def clean_unserved(session: AsyncSession) -> tuple[int, list[str]]:
    """Delete exposed models whose route resolves to no enabled upstream.

    Returns ``(deleted_count, deleted_model_ids)``.
    """
    providers_by_id = {p.id: p for p in await _enabled_providers(session)}
    rows = (await session.execute(select(ExposedModel))).scalars().all()
    removed: list[str] = []
    for exposed in rows:
        route = exposed.route
        if route is None:
            removed.append(exposed.model_id)
            await session.delete(exposed)
            continue
        usable = any(
            entry.enabled
            and entry.provider_id is not None
            and providers_by_id.get(entry.provider_id) is not None
            for layer in route.layers
            for entry in layer.entries
        )
        if not usable:
            removed.append(exposed.model_id)
            await session.delete(exposed)
    if removed:
        await session.flush()
    return len(removed), sorted(removed)
