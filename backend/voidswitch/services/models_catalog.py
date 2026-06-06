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
from voidswitch.services.selector import provider_serves_model


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


def served_model_ids(providers: list[Provider]) -> set[str]:
    """Explicit model ids (and alias-route aliases) served by the providers.

    Wildcards (``*``) are skipped — they match anything but name nothing.
    """
    ids: set[str] = set()
    for provider in providers:
        for name in provider.models or []:
            if isinstance(name, str) and name and name != "*":
                ids.add(name)
        for route in provider.model_routes or []:
            if isinstance(route, dict):
                alias = route.get("alias")
                if isinstance(alias, str) and alias:
                    ids.add(alias)
    return ids


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

    all_ids = served_model_ids(providers) | set(entries)
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
