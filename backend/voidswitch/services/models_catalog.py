"""Platform-wide model catalog.

The *available* models are the union of every enabled provider's model ids
(explicit names plus alias-route aliases, wildcards excluded). On top of that
union we layer optional per-model metadata stored in the ``models`` table — a
description and a custom OpenCode model config. This module merges the two and
keeps the metadata table in sync with what providers actually serve.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.models.db import ModelEntry, Provider
from voidswitch.services.selector import provider_serves_model, routed_upstreams


@dataclass(slots=True)
class CatalogItem:
    """One model id merged with its metadata + the providers serving it."""

    model_id: str
    entry: ModelEntry | None
    providers: list[str]

    @property
    def served(self) -> bool:
        return bool(self.providers)

    @property
    def registered(self) -> bool:
        return self.entry is not None

    @property
    def enabled(self) -> bool:
        return self.entry.enabled if self.entry is not None else True

    @property
    def mapped_id(self) -> str | None:
        return self.entry.mapped_id if self.entry is not None else None

    @property
    def public_id(self) -> str:
        """The id clients see / must call: the mapped alias if set, else the raw id."""
        mapped = self.mapped_id
        return mapped if mapped else self.model_id


def served_model_ids(providers: list[Provider]) -> set[str]:
    """Explicit model ids (and alias-route aliases) served by the providers.

    Wildcards (``*``) are skipped — they match anything but name nothing. A raw
    model id that an alias route hides behind itself (its ``upstream``) is
    skipped too: only the alias is advertised, never the upstream id.
    """
    ids: set[str] = set()
    for provider in providers:
        hidden = routed_upstreams(provider)
        for name in provider.models or []:
            if isinstance(name, str) and name and name != "*" and name not in hidden:
                ids.add(name)
        for route in provider.model_routes or []:
            if isinstance(route, dict):
                alias = route.get("alias")
                if isinstance(alias, str) and alias:
                    ids.add(alias)
    return ids


def _hidden_upstreams(providers: list[Provider]) -> set[str]:
    """Upstream ids hidden behind an alias route on *some* provider but not
    served plainly by *any* provider."""
    served = served_model_ids(providers)
    hidden: set[str] = set()
    for provider in providers:
        hidden |= routed_upstreams(provider)
    return hidden - served


def providers_serving(providers: list[Provider], model_id: str) -> list[str]:
    """Names of the providers that serve ``model_id`` (honours wildcards/routes)."""
    return [p.name for p in providers if provider_serves_model(p, model_id)]


async def _enabled_providers(session: AsyncSession) -> list[Provider]:
    rows = (
        (await session.execute(select(Provider).where(Provider.enabled.is_(True))))
        .scalars()
        .all()
    )
    return list(rows)


async def build_catalog(session: AsyncSession) -> list[CatalogItem]:
    """Every known model id (served + registered), merged with metadata."""
    providers = await _enabled_providers(session)
    entries = {e.model_id: e for e in (await session.execute(select(ModelEntry))).scalars().all()}

    # A stale metadata row for an upstream id that is now hidden behind an alias
    # route (and served by nobody under its raw name) should not resurface in the
    # catalog — only its alias is advertised. The row stays deletable.
    hidden = _hidden_upstreams(providers)
    all_ids = served_model_ids(providers) | (set(entries) - hidden)
    items = [
        CatalogItem(
            model_id=mid,
            entry=entries.get(mid),
            providers=providers_serving(providers, mid),
        )
        for mid in all_ids
    ]
    # Stable, human-friendly ordering.
    items.sort(key=lambda i: i.model_id.lower())
    return items


async def mapping_tables(session: AsyncSession) -> tuple[dict[str, str], set[str]]:
    """Return the gateway's model-aliasing tables.

    * ``alias_to_source`` — public alias → the real (upstream) model id.
    * ``hidden_sources``  — real ids that have an alias, so they are no longer
      callable under their original name (only via the alias).
    """
    result = await session.execute(
        select(ModelEntry.model_id, ModelEntry.mapped_id).where(ModelEntry.mapped_id.is_not(None))
    )
    rows = result.all()
    alias_to_source: dict[str, str] = {}
    hidden_sources: set[str] = set()
    for model_id, mapped_id in rows:
        if not mapped_id:
            continue
        alias_to_source[mapped_id] = model_id
        hidden_sources.add(model_id)
    return alias_to_source, hidden_sources


async def hidden_model_ids(session: AsyncSession) -> set[str]:
    """Model ids not callable under their raw name.

    Combines the metadata-alias hiding (``mapping_tables``) with route-hiding: a
    raw id an alias route hides behind itself on *every* provider that could serve
    it is not advertised, so it must be rejected at the gateway too.
    """
    _, hidden = await mapping_tables(session)
    providers = await _enabled_providers(session)
    return hidden | _hidden_upstreams(providers)


async def clean_unserved(session: AsyncSession) -> tuple[int, list[str]]:
    """Delete metadata rows for model ids no provider serves.

    Returns ``(deleted_count, deleted_model_ids)``. Only touches rows whose
    ``model_id`` is absent from ``served_model_ids()``.
    """
    providers = await _enabled_providers(session)
    served = served_model_ids(providers)
    entries = (await session.execute(select(ModelEntry))).scalars().all()
    unserved = [e for e in entries if e.model_id not in served]
    ids: list[str] = []
    for entry in unserved:
        ids.append(entry.model_id)
        await session.delete(entry)
    if ids:
        await session.flush()
    return len(ids), sorted(ids)


async def sync_from_providers(
    session: AsyncSession, *, added_by: int | None = None, added_by_name: str | None = None
) -> tuple[int, int]:
    """Create metadata rows for any served model id that lacks one.

    Returns ``(added, total)`` where ``total`` is the number of metadata rows
    after the sync. Existing rows are left untouched (descriptions / configs are
    never overwritten), so this is safe to run repeatedly.
    """
    providers = await _enabled_providers(session)
    existing = set(
        (await session.execute(select(ModelEntry.model_id))).scalars().all()
    )
    missing = served_model_ids(providers) - existing
    for model_id in sorted(missing):
        session.add(
            ModelEntry(model_id=model_id, added_by=added_by, added_by_name=added_by_name)
        )
    if missing:
        await session.flush()
    return len(missing), len(existing) + len(missing)
