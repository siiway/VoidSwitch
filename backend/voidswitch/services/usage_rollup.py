"""Incremental usage rollups that back the activity heatmap and its statistics.

Every completed request updates two small aggregate tables in the same
transaction that writes its ``request_logs`` row:

* ``usage_daily`` — one row per (user, UTC day) carrying the summed token count
  and request count. This is what the heatmap, cumulative/peak token figures,
  and the day-streaks are computed from.
* ``session_spans`` — one row per conversation/session carrying its first and
  latest timestamp, from which the "longest task duration" statistic is derived.

Keeping these as standalone rollups (rather than re-aggregating ``request_logs``
on the fly) means the heatmap keeps working even when request logs are pruned,
and lets the two be retained on their own, longer schedule
(``heatmap_retention_days``, at least one year).

The upsert uses the ``ON CONFLICT DO UPDATE`` form, which both SQLite (≥3.24)
and PostgreSQL support, so concurrent requests for the same (user, day) or
session accumulate correctly without a read-modify-write race.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.logging import get_logger
from voidswitch.models.db import SessionSpan, UsageDaily

log = get_logger("services.usage_rollup")

# Guard against a session key longer than the column (a very long client-supplied
# session id). Truncation only affects the per-session span attribution, never the
# daily token totals.
_MAX_SESSION_KEY = 255


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _insert(session: AsyncSession):
    name = session.bind.dialect.name if session.bind is not None else "sqlite"
    return pg_insert if name == "postgresql" else sqlite_insert


async def record_usage(
    session: AsyncSession,
    *,
    user_sub: str | None,
    session_key: str | None,
    tokens: int,
    ts: dt.datetime | None = None,
) -> None:
    """Fold one completed request into the daily + session-span rollups.

    Best-effort: a rollup failure is logged and swallowed so it can never turn a
    successfully-served request into an error. Called exactly once per request
    (at the point its final token count is known).
    """
    ts = ts or _utcnow()
    sub = user_sub or ""
    tokens = max(int(tokens or 0), 0)
    day = ts.strftime("%Y-%m-%d")
    now = _utcnow()

    try:
        ins = _insert(session)

        daily = ins(UsageDaily).values(
            user_sub=sub, day=day, tokens=tokens, requests=1, updated_at=now
        )
        daily = daily.on_conflict_do_update(
            index_elements=[UsageDaily.user_sub, UsageDaily.day],
            set_={
                "tokens": UsageDaily.__table__.c.tokens + daily.excluded.tokens,
                "requests": UsageDaily.__table__.c.requests + daily.excluded.requests,
                "updated_at": now,
            },
        )
        await session.execute(daily)

        key = (session_key or "")[:_MAX_SESSION_KEY]
        if key:
            span = ins(SessionSpan).values(
                session_key=key,
                user_sub=sub,
                started_at=ts,
                last_at=ts,
                requests=1,
                updated_at=now,
            )
            span = span.on_conflict_do_update(
                index_elements=[SessionSpan.session_key],
                set_={
                    # Requests are recorded in roughly increasing ts order, so the
                    # incoming ts is the new latest; started_at is left untouched so
                    # it stays pinned to the session's first request.
                    "last_at": span.excluded.last_at,
                    "requests": SessionSpan.__table__.c.requests + 1,
                    "updated_at": now,
                },
            )
            await session.execute(span)
    except Exception as exc:  # pragma: no cover - defensive; rollups are non-critical
        log.warning("usage_rollup_failed", error=str(exc), user_sub=sub, day=day)
