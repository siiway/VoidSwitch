"""Dashboard health snapshots and opt-in SSE streams."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.api.models import _health_snapshot
from voidswitch.core import sse
from voidswitch.core.auth import get_current_user, is_staff
from voidswitch.core.database import get_database, get_session
from voidswitch.models.db import Node, NodeGroup, NodeHealthSample, User
from voidswitch.services import routing, settings_store, upstream_health

router = APIRouter(prefix="/api/health", tags=["health"])
_WINDOWS = {
    "30m": 1800,
    "1h": 3600,
    "3h": 10800,
    "12h": 43200,
    "1d": 86400,
    "3d": 259200,
    "7d": 604800,
}


async def _node_snapshot(session: AsyncSession, window: str) -> list[dict]:
    seconds = _WINDOWS.get(window, _WINDOWS["1d"])
    since = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=seconds)
    nodes = (await session.execute(select(Node).order_by(Node.id))).scalars().all()
    groups = (await session.execute(select(NodeGroup))).scalars().all()
    memberships: dict[int, list[str]] = {}
    for group in groups:
        for node in await routing.group_nodes(session, group):
            memberships.setdefault(node.id, []).append(group.name)
    samples = (
        (
            await session.execute(
                select(NodeHealthSample)
                .where(NodeHealthSample.ts >= since)
                .order_by(NodeHealthSample.ts.asc())
            )
        )
        .scalars()
        .all()
    )
    by_node: dict[int, list[NodeHealthSample]] = {}
    for sample in samples:
        by_node.setdefault(sample.node_id, []).append(sample)
    alpha = max(0.0, settings_store.get_float("node_rank_alpha", 1.0))
    beta = max(0.0, settings_store.get_float("node_rank_beta", 100.0))
    gamma = max(0.0, settings_store.get_float("node_rank_gamma", 1000.0))
    threshold = max(1, settings_store.get_int("max_proxy_failures", 3))
    result = []
    for node in nodes:
        node_samples = by_node.get(node.id, [])
        score = alpha * (node.latency_ewma or 0.0) + beta * (node.failed_count or 0)
        score += gamma * min(1.0, (node.failed_count or 0) / threshold)
        result.append(
            {
                "id": node.id,
                "url": node.url,
                "type": node.type,
                "note": node.note,
                "enabled": node.enabled,
                "status": node.status,
                "failed_count": node.failed_count,
                "latency_ms": node.latency_ms,
                "latency_ewma": node.latency_ewma,
                "score": score,
                "groups": sorted(set(memberships.get(node.id, []))),
                "last_used_at": node.last_used_at,
                "last_checked_at": node.last_checked_at,
                "disabled_reason": node.disabled_reason,
                "samples": [
                    {
                        "ts": sample.ts,
                        "success": sample.success,
                        "latency_ms": sample.latency_ms,
                        "source": sample.source,
                        "status_code": sample.status_code,
                    }
                    for sample in node_samples
                ],
            }
        )
    return result


async def _snapshot(session: AsyncSession, user: User, tab: str, window: str) -> dict:
    if tab == "nodes":
        if not is_staff(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Node health is staff-only.")
        return {"tab": "nodes", "nodes": await _node_snapshot(session, window)}
    return {"tab": "models", "models": await _health_snapshot(session, user)}


@router.get("")
async def health_snapshot(
    tab: str = Query("models", pattern="^(models|nodes)$"),
    window: str = Query("1d", pattern="^(30m|1h|3h|12h|1d|3d|7d)$"),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    return await _snapshot(session, user, tab, window)


@router.get("/stream")
async def health_stream(
    tab: str = Query("models", pattern="^(models|nodes)$"),
    window: str = Query("1d", pattern="^(30m|1h|3h|12h|1d|3d|7d)$"),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    if tab == "nodes" and not is_staff(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Node health is staff-only.")
    await sse.acquire(user.sub)
    queue = upstream_health.subscribe()

    async def events() -> AsyncIterator[str]:
        try:
            while True:
                async with get_database().session() as session:
                    payload = await _snapshot(session, user, tab, window)
                yield f"data: {json.dumps(payload, default=str)}\n\n"
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(queue.get(), timeout=5.0)
        finally:
            upstream_health.unsubscribe(queue)
            await sse.release(user.sub)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
