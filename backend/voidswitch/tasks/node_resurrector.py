"""Background node resurrector.

Periodically probes ``disabled`` outbound nodes through their node group's probe
URL with a lightweight GET. If a probe succeeds (any HTTP response proves
reachability), the node is re-enabled and its EWMA refreshed.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from voidswitch.constants import NodeStatus
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.models.db import Node, NodeGroup
from voidswitch.services import routing, settings_store
from voidswitch.services.network import probe_route

log = get_logger("tasks.resurrector")


async def run_node_resurrector() -> None:
    # When routing is off an external proxy (e.g. mihomo) handles egress: there
    # is no pool to probe or resurrect, so this task self-disables.
    if not settings_store.get_bool("proxy_switching_enabled", True):
        return
    db = get_database()

    async with db.session() as session:
        nodes = (
            (
                await session.execute(
                    select(Node).where(
                        Node.enabled.is_(True),
                        Node.status == NodeStatus.DISABLED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not nodes:
            return
        # Group lookup map + the group each node belongs to (for its probe URL).
        groups = {g.id: g for g in (await session.execute(select(NodeGroup))).scalars().all()}
        # Build group_id -> list[(node, probe group)] in-memory via collect.
        index = await routing.load_group_index(session)
        node_group_probe: dict[int, tuple[NodeGroup, NodeGroup | Node]] = {}
        for g in groups.values():
            for member in g.members or []:
                if member.node is not None:
                    node_group_probe.setdefault(member.node.id, (g, member.node))
                elif member.source_group_id is not None:
                    src = index.get(member.source_group_id)
                    if src is not None:
                        for sub in (
                            routing.collect_group_nodes(src, all_groups=index) or {}
                        ).values():
                            node_group_probe.setdefault(sub.id, (src, src))

        for node in nodes:
            group, _probe_group = node_group_probe.get(node.id, (None, None))
            await _probe_node(session, node, group)


async def _probe_node(session, node: Node, group: NodeGroup | None) -> None:
    probe_url = routing.group_probe_url(group)
    route = routing.node_route(node)
    ok, latency, _status, error = await probe_route(route, probe_url)
    node.last_checked_at = dt.datetime.now(dt.UTC)
    node.latency_ms = latency
    routing.update_node_latency(node, latency)
    routing.decay_ewma(node)
    if ok:
        node.status = NodeStatus.ACTIVE.value
        node.failed_count = 0
        node.disabled_reason = None
        log.info("node_resurrected", node_id=node.id, latency_ms=round(latency))
    else:
        node.disabled_reason = error
