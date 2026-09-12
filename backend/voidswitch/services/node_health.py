"""Persistent node-health samples used by the moderator health dashboard."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.models.db import Node, NodeHealthSample


def add_sample(
    session: AsyncSession,
    node: Node | None,
    *,
    success: bool,
    latency_ms: float | None,
    source: str,
    status_code: int | None = None,
    error: str | None = None,
) -> None:
    if node is None or node.id is None:
        return
    session.add(
        NodeHealthSample(
            node_id=node.id,
            source=source,
            success=success,
            latency_ms=latency_ms,
            status_code=status_code,
            error=(error or "")[:255] or None,
        )
    )
