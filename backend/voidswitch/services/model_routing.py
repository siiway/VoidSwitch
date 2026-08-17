"""Model routing: exposed → route flow → upstream resolution + config merge.

An exposed model's :class:`Route` is a vertical flow: the user-requested model
sits on top, and each ordered :class:`RouteLayer` below is a *fallback pool* of
upstream :class:`RoutePoolEntry` refs (provider + upstream_model). Within a
layer, entries are tried in weighted-random order; failures eligible for
fallback (429/404/5xx …) move down the flow until the retry budget is spent.
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.models.db import ExposedModel, Provider, Route, RouteLayer

# models.dev entry keys we understand (registry entry shape is loose across
# providers; extract the intersection that maps onto our config fields).
_MD_TEXT_FIELDS = ("name", "description")
_MD_LIMIT_KEYS = ("context", "input", "output")
_MD_CAP_KEYS = ("reasoning", "image", "audio", "tool", "text")


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (nested dicts combine;
    lists/scalars replace). Inputs are not mutated."""
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _norm_md(md: dict | None) -> dict:
    """Normalise a models.dev registry entry into our config vocabulary.

    Registry entries vary: some carry ``name``/``description``, many carry
    ``limit.context``, a few ``modalities``/``reasoning``. We keep only what we
    can project onto the opencode config block, so an upstream model that lacks
    rich metadata simply contributes nothing (defaults win).
    """
    if not isinstance(md, dict):
        return {}
    out: dict[str, Any] = {}
    name = md.get("name")
    if isinstance(name, str) and name:
        out["name"] = name
    desc = md.get("description")
    if isinstance(desc, str) and desc:
        out["description"] = desc
    limit = md.get("limit")
    if isinstance(limit, dict):
        lim: dict[str, Any] = {}
        for key in _MD_LIMIT_KEYS:
            val = limit.get(key)
            if isinstance(val, (int, float)) and val > 0:
                lim[key] = int(val)
        if lim:
            out["limit"] = lim
    if md.get("reasoning") is True:
        out["reasoning"] = True
    return out


def build_opencode_config(exposed: ExposedModel, models_dev_entry: dict | None) -> dict:
    """The merged OpenCode model block shipped to the plugin and /v1/models.

    Precedence (high → low): structured fields → custom ``opencode_config`` →
    models.dev placeholder → (plugin defaults, applied on the client).
    """
    config: dict[str, Any] = {}
    # Base: models.dev placeholder (never overrides anything the operator set).
    base = _norm_md(models_dev_entry)
    config = _deep_merge(config, base)
    # Custom config deep-merged in the middle.
    if exposed.opencode_config:
        config = _deep_merge(config, exposed.opencode_config)
    # Structured fields (highest).
    if exposed.display_name:
        config["name"] = exposed.display_name
    limit: dict[str, Any] = {}
    if exposed.limit_context:
        limit["context"] = exposed.limit_context
    if exposed.limit_input:
        limit["input"] = exposed.limit_input
    if exposed.limit_output:
        limit["output"] = exposed.limit_output
    if limit:
        config["limit"] = _deep_merge(config.get("limit") or {}, limit)
    if exposed.reasoning is not None:
        config["reasoning"] = exposed.reasoning
    if exposed.capabilities:
        config["capabilities"] = _deep_merge(
            config.get("capabilities") or {}, exposed.capabilities
        )
    if exposed.modalities:
        config["modalities"] = _deep_merge(
            config.get("modalities") or {}, exposed.modalities
        )
    return config


def weighted_entries(layer: RouteLayer, rng: random.Random | None = None) -> list[Any]:
    """Enabled entries of a layer in weighted-random order (distinct, no repeat).

    A disabled entry or a disabled/missing provider is dropped up front — the
    pool only ever contains upstreams that could actually serve a request.
    """
    entries = [
        e
        for e in layer.entries
        if e.enabled
        and e.provider is not None
        and e.provider.enabled
    ]
    if len(entries) <= 1:
        return entries
    r = rng if rng is not None else random
    pool = list(entries)
    ordered: list[Any] = []
    while pool:
        weights = [max(1, int(e.weight or 1)) for e in pool]
        choice = r.choices(pool, weights=weights, k=1)[0]
        ordered.append(choice)
        pool.remove(choice)
    return ordered


async def get_or_create_route(
    session: AsyncSession, exposed_model: ExposedModel
) -> Route:
    """A model's route, creating an empty one if missing (idempotent)."""
    route = (
        await session.execute(
            select(Route).where(Route.exposed_model_id == exposed_model.id)
        )
    ).scalar_one_or_none()
    if route is not None:
        return route
    route = Route(exposed_model_id=exposed_model.id)
    session.add(route)
    await session.flush()
    return route


async def resolve_route(
    session: AsyncSession, exposed_model: ExposedModel
) -> Route:
    """Load the dispatch plan for an exposed model with providers (keys loaded).

    Providers referenced by pool entries are loaded through a dedicated query so
    their ``keys`` collection is populated for the dispatcher (selectin
    relationships never lazy-load in async). Returns the route object whose
    layers/entries are already ORM-linked to the same session.
    """
    route = await get_or_create_route(session, exposed_model)
    provider_ids = {
        e.provider_id
        for layer in route.layers
        for e in layer.entries
        if e.provider_id is not None
    }
    if provider_ids:
        rows = (
            await session.execute(
                select(Provider).where(Provider.id.in_(provider_ids))
            )
        ).scalars().all()
        by_id = {p.id: p for p in rows}
        for layer in route.layers:
            for entry in layer.entries:
                if entry.provider_id in by_id:
                    entry.provider = by_id[entry.provider_id]
    return route
