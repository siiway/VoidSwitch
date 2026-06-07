"""Usage analytics — call statistics over time and per caller/token/model.

Staff see platform-wide numbers; members see only their own traffic. The data
is derived entirely from ``request_logs``: a few grouped aggregate queries, kept
portable across SQLite and PostgreSQL by picking the right date-format function
for the active dialect.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import ColumnElement, Row, Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.auth import get_current_user, is_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import RequestLog, User, VoidToken
from voidswitch.models.schemas import (
    UsageAnalyticsOut,
    UsageBucket,
    UsageGroupRow,
    UsageTotals,
)

router = APIRouter(prefix="/api/usage", tags=["usage"])

# How many trailing buckets of each granularity to return.
_LIMITS = {"day": 30, "week": 12, "month": 12, "year": 5}

# Per-dialect strftime/to_char templates for each granularity. SQLite stores the
# %W week (Mon-based, 00-53); PostgreSQL uses the ISO week, close enough for a
# rolling overview.
_SQLITE_FMT = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m", "year": "%Y"}
_PG_FMT = {"day": "YYYY-MM-DD", "week": 'IYYY-"W"IW', "month": "YYYY-MM", "year": "YYYY"}


def _period_expr(dialect: str, granularity: str) -> ColumnElement[str]:
    if dialect == "postgresql":
        return func.to_char(RequestLog.ts, _PG_FMT[granularity])
    # SQLite (default) and anything else that speaks strftime.
    return func.strftime(_SQLITE_FMT[granularity], RequestLog.ts)


# Reusable aggregate selectors over a set of request_logs rows.
_SUCCESS_SUM = func.coalesce(func.sum(case((RequestLog.success.is_(True), 1), else_=0)), 0)
_COUNT = func.count(RequestLog.id)
_PROMPT = func.coalesce(func.sum(RequestLog.prompt_tokens), 0)
_COMPLETION = func.coalesce(func.sum(RequestLog.completion_tokens), 0)
_TOKENS = func.coalesce(func.sum(RequestLog.total_tokens), 0)


def _scope(stmt: Select, user: User) -> Select:
    """Restrict a query to the caller's own traffic unless they are staff."""
    if is_staff(user):
        return stmt
    return stmt.where(RequestLog.user_sub == user.sub)


def _totals_from_row(row: Sequence) -> dict:
    requests, success, prompt, completion, total = (int(v or 0) for v in row)
    return {
        "requests": requests,
        "success": success,
        "failures": requests - success,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


async def _totals(session: AsyncSession, user: User) -> UsageTotals:
    stmt = _scope(select(_COUNT, _SUCCESS_SUM, _PROMPT, _COMPLETION, _TOKENS), user)
    row = (await session.execute(stmt)).one()
    return UsageTotals(**_totals_from_row(row))


async def _series(
    session: AsyncSession, user: User, dialect: str, granularity: str
) -> list[UsageBucket]:
    period = _period_expr(dialect, granularity).label("period")
    stmt = _scope(
        select(period, _COUNT, _SUCCESS_SUM, _PROMPT, _COMPLETION, _TOKENS),
        user,
    )
    stmt = (
        stmt.group_by(period).order_by(period.desc()).limit(_LIMITS[granularity])
    )
    rows = (await session.execute(stmt)).all()
    buckets = [
        UsageBucket(period=str(r[0]), **_totals_from_row(r[1:]))
        for r in rows
        if r[0] is not None
    ]
    buckets.reverse()  # chronological order for charting
    return buckets


async def _group(
    session: AsyncSession, user: User, column: Any, *, limit: int = 100
) -> Sequence[Row[Any]]:
    stmt = _scope(
        select(column, _COUNT, _SUCCESS_SUM, _PROMPT, _COMPLETION, _TOKENS),
        user,
    )
    stmt = stmt.group_by(column).order_by(_COUNT.desc()).limit(limit)
    return (await session.execute(stmt)).all()


@router.get("", response_model=UsageAnalyticsOut)
async def usage_analytics(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> UsageAnalyticsOut:
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"

    totals = await _totals(session, user)
    daily = await _series(session, user, dialect, "day")
    weekly = await _series(session, user, dialect, "week")
    monthly = await _series(session, user, dialect, "month")
    yearly = await _series(session, user, dialect, "year")

    user_rows = await _group(session, user, RequestLog.user_sub)
    token_rows = await _group(session, user, RequestLog.token_id)
    model_rows = await _group(session, user, RequestLog.model)

    # Resolve human-friendly labels for users and tokens in two batched queries.
    subs = {r[0] for r in user_rows if r[0]}
    user_names: dict[str, str] = {}
    if subs:
        for u in (await session.execute(select(User).where(User.sub.in_(subs)))).scalars().all():
            user_names[u.sub] = u.name or u.username or u.email or u.sub
    token_ids = {r[0] for r in token_rows if r[0] is not None}
    token_names: dict[int, str] = {}
    if token_ids:
        for tid, tname in (
            await session.execute(
                select(VoidToken.id, VoidToken.name).where(VoidToken.id.in_(token_ids))
            )
        ).all():
            token_names[tid] = tname

    by_user = [
        UsageGroupRow(
            key=str(r[0]) if r[0] else "",
            label=user_names.get(r[0], r[0]) if r[0] else "(anonymous)",
            **_totals_from_row(r[1:]),
        )
        for r in user_rows
    ]
    by_token = [
        UsageGroupRow(
            key=str(r[0]) if r[0] is not None else "",
            label=token_names.get(r[0], f"#{r[0]}") if r[0] is not None else "(none)",
            **_totals_from_row(r[1:]),
        )
        for r in token_rows
    ]
    by_model = [
        UsageGroupRow(
            key=r[0] or "",
            label=r[0] or "(unknown)",
            **_totals_from_row(r[1:]),
        )
        for r in model_rows
    ]

    return UsageAnalyticsOut(
        scope="all" if is_staff(user) else "self",
        totals=totals,
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        yearly=yearly,
        by_user=by_user,
        by_token=by_token,
        by_model=by_model,
    )
