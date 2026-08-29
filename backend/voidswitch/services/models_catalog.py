"""Exposed model catalog.

The public catalog is the set of :class:`ExposedModel` rows — the only ids
clients ever see. Upstream ids (``slug/model``) are internal: they appear only
as route-pool refs and are never advertised. This module lists exposed models
and cleans up exposed models with no reachable upstream.

Model creation is deliberately **not** automatic: new upstream ids arriving at a
provider never mint an :class:`ExposedModel` row on their own. Operators either
create models by hand, or enable provider passthrough to surface them directly.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.models.db import ExposedModel, Provider

_PASSTHROUGH_RE = re.compile(
    r"^(?P<exposed>[^\s@]+?)(?:\s*=>\s*(?P<upstream>[^\s@]+?))?(?:\s*@\s*(?P<pool>\S+))?$"
)


async def _enabled_providers(session: AsyncSession) -> list[Provider]:
    rows = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True)))).scalars().all()
    )
    return list(rows)


def passthrough_model_ids(providers: list[Provider]) -> set[str]:
    """The full ``slug/exposed-id`` ids served directly by passthrough providers.

    A passthrough row's ``exposed`` part is what becomes the id after the
    provider slug (``exposed-id => original-id @ pool`` — only the leading
    ``exposed-id`` matters for the surfaced id).
    """
    ids: set[str] = set()
    for provider in providers:
        if not provider.passthrough_enabled:
            continue
        for entry in provider.passthrough_models or []:
            if not isinstance(entry, str):
                continue
            m = _PASSTHROUGH_RE.match(entry.strip())
            exposed = (m.group("exposed") if m else entry.strip()).strip()
            if exposed:
                ids.add(f"{provider.slug}/{exposed}")
    return ids


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


async def clean_unserved(session: AsyncSession) -> tuple[int, list[str]]:
    """Delete exposed models whose route resolves to no enabled upstream.

    A model whose id is served by an enabled passthrough provider is *not*
    unserved (passthrough forwards it directly), so it is left alone even if its
    local route is empty. Returns ``(deleted_count, deleted_model_ids)``.
    """
    providers = await _enabled_providers(session)
    providers_by_id = {p.id: p for p in providers}
    passthrough = passthrough_model_ids(providers)
    rows = (await session.execute(select(ExposedModel))).scalars().all()
    removed: list[str] = []
    for exposed in rows:
        if exposed.model_id in passthrough:
            continue
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
