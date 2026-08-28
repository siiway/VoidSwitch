"""Outbound routing system: node groups, inheritance, dynamic ranking.

Replaces the old flat proxy pool. Every outbound request — provider upstream
calls and system requests alike — belongs to a :class:`NodeGroup`: a freely
created group that picks *nodes* from the global pool and/or *inherits* the
members of other groups (live reference, like Python class inheritance). Idle
health probes (``probe_url`` per group) plus per-request outcomes feed a dynamic
score so the group orders its nodes by latency + stability (a Fallback/Url-Test
hybrid). Requests take the ordered list front-to-back and fall through on
failure.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import NodeStatus, NodeType
from voidswitch.models.db import Node, NodeGroup, Provider
from voidswitch.services import settings_store
from voidswitch.services.network import Route

DEFAULT_GROUP_SLUG = "default"
SYSTEM_GROUP_SLUG = "system"

# How aggressively a new latency sample moves the EWMA (0 < alpha < 1).
_EWMA_ALPHA = 0.2


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# --------------------------------------------------------------------------- #
# Group seeding
# --------------------------------------------------------------------------- #


async def ensure_seeded_groups(session: AsyncSession) -> None:
    """Idempotently create the ``default`` and ``system`` node groups.

    The default group is picked up by any provider with no explicit
    ``node_group_id``; the system group carries system requests. A group with no
    members falls back to **direct** — so even a misconfigured routing setup can
    never lock an operator out of login/Prism/OAuth.
    """
    for slug, name, is_system in (
        (DEFAULT_GROUP_SLUG, "Default", False),
        (SYSTEM_GROUP_SLUG, "System", True),
    ):
        exists = (await session.execute(select(NodeGroup.id).where(NodeGroup.slug == slug))).first()
        if exists is None:
            session.add(NodeGroup(slug=slug, name=name, is_system=is_system))
    await session.flush()


async def _group_by_slug(session: AsyncSession, slug: str) -> NodeGroup | None:
    return (
        await session.execute(select(NodeGroup).where(NodeGroup.slug == slug))
    ).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Group expansion (inheritance, cycle-safe)
# --------------------------------------------------------------------------- #


def _expand_members(group: NodeGroup) -> dict[int, Node]:
    """Flatten a group's own rows into a dict of live ``Node`` objects.

    Direct rows carry ``node`` (already loaded selectin); inherited rows point
    at another group whose nodes are expanded recursively. Cycle / duplicate
    protection happens in :func:`collect_group_nodes` below.
    """
    nodes: dict[int, Node] = {}
    for member in group.members or []:
        if member.node is not None:
            nodes.setdefault(member.node.id, member.node)
    return nodes


def collect_group_nodes(
    group: NodeGroup | None,
    *,
    all_groups: dict[int, NodeGroup] | None = None,
    _path: set[int] | None = None,
) -> dict[int, Node]:
    """Recursively collect every node reachable from ``group``.

    * direct members are included as-is;
    * inherited groups are expanded transitively (live reference);
    * a group that is already on the current expansion path (a cycle) is
      skipped — membership is still expressible, cycles just can't recurse.
    """
    if group is None:
        return {}
    path = _path if _path is not None else set()
    all_groups = all_groups or {}
    if group.id in path:
        return {}
    nodes: dict[int, Node] = {}
    for member in group.members or []:
        if member.node is not None:
            nodes.setdefault(member.node.id, member.node)
        elif member.source_group_id is not None:
            src = all_groups.get(member.source_group_id)
            if src is None:
                continue
            sub = collect_group_nodes(src, all_groups=all_groups, _path=path | {group.id})
            for nid, node in sub.items():
                nodes.setdefault(nid, node)
    return nodes


async def load_group_index(session: AsyncSession) -> dict[int, NodeGroup]:
    """All groups (with members eagerly loaded) by id, for recursive expansion."""
    groups = (await session.execute(select(NodeGroup))).scalars().all()
    return {g.id: g for g in groups}


async def group_nodes(
    session: AsyncSession,
    group: NodeGroup | None,
    *,
    only_enabled: bool = False,
) -> list[Node]:
    """The effective node list of a group, in storage order (unsorted).

    ``None`` (group missing / not yet seeded) yields the empty list — callers
    fall back to direct.
    """
    if group is None:
        return []
    index = await load_group_index(session)
    nodes = collect_group_nodes(group, all_groups=index)
    ordered = list(nodes.values())
    if only_enabled:
        ordered = [n for n in ordered if n.enabled and n.status == NodeStatus.ACTIVE.value]
    return ordered


# --------------------------------------------------------------------------- #
# Dynamic ranking (Fallback + Url-Test hybrid)
# --------------------------------------------------------------------------- #


def rank_nodes(nodes: Iterable[Node]) -> list[Node]:
    """Order nodes best-first for a request.

    score = alpha·ewma_latency_ms + beta·failed_count + gamma·failure-proximity.
    Ascending score wins; ties spread by ``weight`` (heavier first) then id. The
    proxied request walks this list front-to-back, so a node that has been slow
    or flaky drifts to the back automatically.
    """
    alpha = max(0.0, settings_store.get_float("node_rank_alpha", 1.0))
    beta = max(0.0, settings_store.get_float("node_rank_beta", 100.0))
    gamma = max(0.0, settings_store.get_float("node_rank_gamma", 1000.0))
    threshold = max(1, settings_store.get_int("max_proxy_failures", 3))

    def _score(n: Node) -> float:
        ewma = n.latency_ewma if n.latency_ewma is not None else 0.0
        proximity = min(1.0, (n.failed_count or 0) / threshold)
        return alpha * ewma + beta * (n.failed_count or 0) + gamma * proximity

    ordered = list(nodes)
    ordered.sort(key=lambda n: (_score(n), -(n.weight or 1), n.id or 0))
    return ordered


def update_node_latency(node: Node, latency_ms: float) -> None:
    """Fold one latency sample into the node's EWMA."""
    now = _utcnow()
    node.last_used_at = now
    node.latency_ms = round(latency_ms, 1)
    prev = node.latency_ewma
    node.latency_ewma = latency_ms if prev is None else prev + _EWMA_ALPHA * (latency_ms - prev)


def penalize_node(node: Node, reason: str, *, auto_disable: bool = True) -> None:
    """Bump a node's failure counter, disabling it past ``max_proxy_failures``.

    With health-checking off (external egress manager) failures are counted but
    never park the node — matching the old proxy behaviour.
    """
    if node is None:
        return
    node.failed_count = (node.failed_count or 0) + 1
    node.last_checked_at = _utcnow()
    if auto_disable and node.failed_count >= max(
        1, settings_store.get_int("max_proxy_failures", 3)
    ):
        node.status = NodeStatus.DISABLED.value
        node.disabled_reason = reason


def reward_node(node: Node) -> None:
    if node is None:
        return
    if node.failed_count:
        node.failed_count = 0
    node.last_used_at = _utcnow()


def decay_ewma(node: Node) -> None:
    """Push a node's EWMA lazily toward its last raw latency while idling.

    Prevents a node that was slow *once* (during a probe storm) from hogging the
    bottom of the ranking forever without new measurements.
    """
    if node.latency_ewma is None or node.latency_ms is None:
        return
    node.latency_ewma = node.latency_ewma + 0.1 * (node.latency_ms - node.latency_ewma)


# --------------------------------------------------------------------------- #
# Probe URL resolution
# --------------------------------------------------------------------------- #


def group_probe_url(group: NodeGroup | None) -> str:
    return ((group.probe_url if group else "") or "").strip() or settings_store.get_str(
        "node_default_probe_url", "https://api.openai.com/v1/models"
    )


def group_probe_interval(group: NodeGroup | None) -> int:
    if group is not None and group.probe_interval_seconds > 0:
        return group.probe_interval_seconds
    return max(15, settings_store.get_int("node_probe_interval_seconds", 120))


async def group_probe_targets(
    session: AsyncSession, group: NodeGroup | None
) -> list[tuple[Node, NodeGroup | None]]:
    """(node, group) pairs for idle probing, restricted to live nodes.

    A node that appears through inheritance is probed under the *referencing*
    group's probe URL (the group whose membership pulled it in), which is what
    the resurrector uses to re-enable it.
    """
    if group is None:
        return []
    index = await load_group_index(session)
    targets: dict[int, tuple[Node, NodeGroup | None]] = {}

    def walk(g: NodeGroup, referrer: NodeGroup | None, path: set[int]) -> None:
        if g.id in path:
            return
        for member in g.members or []:
            if member.node is not None:
                targets.setdefault(member.node.id, (member.node, referrer or g))
            elif member.source_group_id is not None:
                src = index.get(member.source_group_id)
                if src is not None:
                    walk(src, referrer or src, path | {g.id})

    walk(group, group, set())
    return list(targets.values())


# --------------------------------------------------------------------------- #
# Route resolution
# --------------------------------------------------------------------------- #


def node_route(node: Node) -> Route:
    """The :class:`network.Route` for a node.

    AGENT nodes currently reuse the node URL as an HTTP forward-proxy address
    (compatible with ``voidswitch-agent --mode connect``); the custom relay
    transport is wired in with the agent milestone.
    """
    if node.type == NodeType.DIRECT.value or not node.url:
        return Route()
    return Route(
        proxy_url=node.url or None,
        local_address=node.local_address,
        agent_node_id=node.id if node.type == NodeType.AGENT.value else None,
    )


def routes_for_nodes(nodes: list[Node]) -> list[tuple[Route, Node | None]]:
    return [(node_route(n), n) for n in nodes]


async def group_routes(
    session: AsyncSession,
    group: NodeGroup | None,
    *,
    include_disabled: bool = False,
) -> list[tuple[Route, Node | None]]:
    """Best-first outbound routes for a node group.

    An empty group (or ``None``) yields ``[direct]`` — there is always at least
    one usable route, so a routing misconfiguration degrades to a direct
    connection instead of a hard failure.
    """
    nodes = await group_nodes(session, group, only_enabled=not include_disabled)
    if not nodes:
        return [(Route(), None)]
    return routes_for_nodes(rank_nodes(nodes))


async def provider_routes(session: AsyncSession, provider: Provider | None) -> NodeGroup | None:
    """The node group a provider's upstream requests use (default group fallback)."""
    if provider is not None and provider.node_group_id is not None:
        group = await session.get(NodeGroup, provider.node_group_id)
        if group is not None:
            return group
    return await _group_by_slug(session, DEFAULT_GROUP_SLUG)


async def system_routes(session: AsyncSession) -> list[tuple[Route, Node | None]]:
    """Outbound routes for system requests (Prism, balance probes, OAuth …).

    Uses the System group when it has usable nodes; empty System group degrades
    to direct so login/OAuth can never be bricked by a routing mistake.
    """
    if not settings_store.get_bool("proxy_switching_enabled", True):
        # Routing off → single fixed route (static proxy / env / direct).
        from voidswitch.services.selector import static_routes

        return static_routes(settings_store.get_str("static_proxy_url", ""))
    system = await _group_by_slug(session, SYSTEM_GROUP_SLUG)
    return await group_routes(session, system)


async def system_group(session: AsyncSession) -> NodeGroup | None:
    return await _group_by_slug(session, SYSTEM_GROUP_SLUG)


async def default_group(session: AsyncSession) -> NodeGroup | None:
    return await _group_by_slug(session, DEFAULT_GROUP_SLUG)


async def system_client() -> tuple[Any, Route, Node | None]:
    """A pooled outbound client routed through the System node group.

    Resolves the System group routes in its own session (callers may not have
    one — background tasks, key-management API) and returns ``(client, route,
    node)``. Callers should not hold the returned client between requests beyond
    their immediate use; the shared pool manages lifetime.
    """
    from voidswitch.core.database import get_database
    from voidswitch.services.network import get_pool

    db = get_database()
    async with db.session() as session:
        routes = await system_routes(session)
    route, node = routes[0]
    client = await get_pool().get(route, connect_timeout=15.0, read_timeout=30.0)
    return client, route, node
