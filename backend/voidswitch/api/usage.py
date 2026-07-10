"""Usage analytics — call statistics over time and per caller/token/model.

Staff see platform-wide numbers; members see only their own traffic. The data
is derived entirely from ``request_logs``: a few grouped aggregate queries, kept
portable across SQLite and PostgreSQL by picking the right date-format function
for the active dialect.
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import ColumnElement, Row, Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.auth import get_current_user, is_staff, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import RequestLog, SessionSpan, UsageDaily, User, VoidToken
from voidswitch.models.schemas import (
    HeatmapBundleOut,
    HeatmapDay,
    HeatmapOut,
    HeatmapStats,
    UsageAnalyticsOut,
    UsageBucket,
    UsageGroupRow,
    UsageTotals,
)
from voidswitch.services import settings_store

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

    # Resolve human-friendly labels for users and tokens in batched queries.
    subs = {r[0] for r in user_rows if r[0]}
    user_names: dict[str, str] = {}
    if subs:
        for u in (await session.execute(select(User).where(User.sub.in_(subs)))).scalars().all():
            label = u.username or u.name or u.email or u.sub
            user_names[u.sub] = f"{label}#{u.id}"
    token_ids = {r[0] for r in token_rows if r[0] is not None}
    token_names: dict[int, str] = {}
    token_owners: dict[int, str | None] = {}
    if token_ids:
        for tid, tname, uid in (
            await session.execute(
                select(VoidToken.id, VoidToken.name, VoidToken.user_id).where(
                    VoidToken.id.in_(token_ids)
                )
            )
        ).all():
            token_names[tid] = tname
            token_owners[tid] = uid

    user_by_id: dict[int, str] = {}
    owner_ids = {o for o in token_owners.values() if o is not None}
    if owner_ids:
        for u in (
            await session.execute(select(User).where(User.id.in_(owner_ids)))
        ).scalars().all():
            label = u.username or u.name or u.email or u.sub
            user_by_id[u.id] = f"{label}#{u.id}"

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
            label=(
                f"{token_names[r[0]]}#{r[0]}"
                if r[0] is not None and r[0] in token_names
                else f"#{r[0]}" if r[0] is not None else "(none)"
            ),
            sublabel=(
                user_by_id.get(token_owners.get(r[0]))
                if r[0] is not None and token_owners.get(r[0]) is not None
                else None
            ),
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


# --------------------------------------------------------------------------- #
# Activity heatmap
# --------------------------------------------------------------------------- #

# Fallback display window when retention is "keep forever" (0): still show a year.
_DEFAULT_HEATMAP_WINDOW = 365


def _dialect(session: AsyncSession) -> str:
    return session.bind.dialect.name if session.bind is not None else "sqlite"


def _streaks(active_days: list[str], today: dt.date) -> tuple[int, int]:
    """Return (current_streak, longest_streak) over a sorted list of active days.

    A day counts when it saw any token usage. The current streak is the run of
    consecutive days ending today (or yesterday, so the count doesn't drop to
    zero simply because today isn't over yet).
    """
    if not active_days:
        return 0, 0
    dates = [dt.date.fromisoformat(d) for d in active_days]
    dateset = set(dates)

    longest = 1
    run = 1
    for prev, cur in itertools.pairwise(dates):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)

    if today in dateset:
        anchor = today
    elif (today - dt.timedelta(days=1)) in dateset:
        anchor = today - dt.timedelta(days=1)
    else:
        return 0, longest

    current = 0
    cursor = anchor
    while cursor in dateset:
        current += 1
        cursor -= dt.timedelta(days=1)
    return current, longest


async def _heatmap_data(
    session: AsyncSession,
    *,
    user_sub: str | None,
    scope: str,
    label: str | None = None,
) -> HeatmapOut:
    """Build a heatmap payload. ``user_sub=None`` aggregates the whole site."""
    dialect = _dialect(session)
    retention = settings_store.get_int("heatmap_retention_days", _DEFAULT_HEATMAP_WINDOW)
    window = retention if retention > 0 else _DEFAULT_HEATMAP_WINDOW
    today = dt.datetime.now(dt.UTC).date()
    cutoff_day = (today - dt.timedelta(days=window - 1)).strftime("%Y-%m-%d")

    day_stmt = select(
        UsageDaily.day,
        func.coalesce(func.sum(UsageDaily.tokens), 0),
        func.coalesce(func.sum(UsageDaily.requests), 0),
    ).where(UsageDaily.day >= cutoff_day)
    if user_sub is not None:
        day_stmt = day_stmt.where(UsageDaily.user_sub == user_sub)
    day_stmt = day_stmt.group_by(UsageDaily.day).order_by(UsageDaily.day)
    rows = (await session.execute(day_stmt)).all()
    days = [
        HeatmapDay(date=str(r[0]), tokens=int(r[1] or 0), requests=int(r[2] or 0))
        for r in rows
        if r[0]
    ]

    cumulative = sum(d.tokens for d in days)
    peak = max((d.tokens for d in days), default=0)
    active = sorted(d.date for d in days if d.tokens > 0)
    current_streak, longest_streak = _streaks(active, today)

    # Longest session/task span (in seconds). Time-diff arithmetic differs per
    # dialect; both reduce to a scalar max over the session spans.
    if dialect == "postgresql":
        duration = func.extract("epoch", SessionSpan.last_at - SessionSpan.started_at)
    else:
        duration = (
            func.julianday(SessionSpan.last_at) - func.julianday(SessionSpan.started_at)
        ) * 86400.0
    span_stmt = select(func.max(duration))
    if user_sub is not None:
        span_stmt = span_stmt.where(SessionSpan.user_sub == user_sub)
    longest_task = (await session.execute(span_stmt)).scalar()

    return HeatmapOut(
        scope=scope,
        retention_days=retention,
        window_days=window,
        stats=HeatmapStats(
            cumulative_tokens=cumulative,
            peak_tokens=peak,
            longest_task_seconds=int(longest_task or 0),
            current_streak=current_streak,
            longest_streak=longest_streak,
            active_days=len(active),
        ),
        days=days,
        label=label,
    )


@router.get("/heatmap", response_model=HeatmapBundleOut)
async def heatmap_bundle(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> HeatmapBundleOut:
    """The caller's own activity heatmap, plus the site-wide one for staff."""
    personal = await _heatmap_data(session, user_sub=user.sub, scope="self")
    site = (
        await _heatmap_data(session, user_sub=None, scope="site")
        if is_staff(user)
        else None
    )
    return HeatmapBundleOut(personal=personal, site=site)


@router.get("/heatmap/user", response_model=HeatmapOut)
async def heatmap_for_user(
    sub: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> HeatmapOut:
    """A specific user's activity heatmap (staff only) — powers the stats popup."""
    subject = (
        await session.execute(select(User).where(User.sub == sub))
    ).scalar_one_or_none()
    if subject is not None:
        base = subject.username or subject.name or subject.email or subject.sub
        label = f"{base}#{subject.id}"
    else:
        label = sub
    return await _heatmap_data(session, user_sub=sub, scope="user", label=label)
