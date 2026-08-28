"""Admin: dashboard summary statistics."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.constants import KeyStatus, NodeStatus
from voidswitch.core.auth import require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import ApiKey, Node, Provider, RequestLog, User, VoidToken
from voidswitch.models.schemas import StatsOut

router = APIRouter(prefix="/api/admin/stats", tags=["admin:stats"])


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


def _since_24h(session: AsyncSession):
    """Database-native expression for "24 hours ago".

    Uses the DB clock so the comparison stays entirely server-side, avoiding
    Python↔DB timezone / type-mapping surprises that previously caused the
    24h window to be wider than intended (especially on SQLite)."""
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    if dialect == "postgresql":
        return func.now() - text("INTERVAL '24 hours'")
    return func.datetime("now", "-24 hours")


@router.get("", response_model=StatsOut)
async def stats(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> StatsOut:
    since = _since_24h(session)

    providers = await _count(session, select(func.count(Provider.id)))
    total_keys = await _count(session, select(func.count(ApiKey.id)))
    active_keys = await _count(
        session,
        select(func.count(ApiKey.id)).where(ApiKey.status == KeyStatus.ACTIVE.value),
    )
    total_proxies = await _count(session, select(func.count(Node.id)))
    active_proxies = await _count(
        session,
        # A node is "active" only when enabled AND marked active — the routing
        # and resurrector both require enabled, but the dashboard's disable
        # action leaves ``status`` untouched, so counting status alone would
        # over-report.
        select(func.count(Node.id)).where(
            Node.enabled.is_(True), Node.status == NodeStatus.ACTIVE.value
        ),
    )
    tokens = await _count(
        session, select(func.count(VoidToken.id)).where(VoidToken.deleted.is_(False))
    )

    requests_24h = await _count(
        session, select(func.count(RequestLog.id)).where(RequestLog.ts >= since)
    )
    success_24h = await _count(
        session,
        select(func.count(RequestLog.id)).where(
            RequestLog.ts >= since, RequestLog.success.is_(True)
        ),
    )
    tokens_24h = await _count(
        session,
        select(func.coalesce(func.sum(RequestLog.total_tokens), 0)).where(RequestLog.ts >= since),
    )
    avg_first_token_ms_24h = (
        await session.execute(
            select(func.avg(RequestLog.first_token_ms)).where(
                RequestLog.ts >= since,
                RequestLog.success.is_(True),
                RequestLog.stream.is_(True),
                RequestLog.first_token_ms.isnot(None),
            )
        )
    ).scalar_one()

    return StatsOut(
        providers=providers,
        active_keys=active_keys,
        total_keys=total_keys,
        active_proxies=active_proxies,
        total_proxies=total_proxies,
        tokens=tokens,
        requests_24h=requests_24h,
        success_24h=success_24h,
        failures_24h=requests_24h - success_24h,
        tokens_24h=tokens_24h,
        success_rate_24h=round(success_24h / requests_24h * 100, 1) if requests_24h else 0.0,
        avg_first_token_ms_24h=(
            round(avg_first_token_ms_24h, 1) if avg_first_token_ms_24h is not None else None
        ),
        avg_tokens_per_request_24h=(round(tokens_24h / requests_24h, 1) if requests_24h else 0.0),
    )
