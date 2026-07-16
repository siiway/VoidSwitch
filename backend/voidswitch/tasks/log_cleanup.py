"""Background log retention.

Periodically deletes audit-log and request-log rows older than the configured
retention windows, so a long-running deployment doesn't accumulate unbounded
history on disk. Each window is independent and disabled (``0`` days) by default;
operators opt in from the dashboard Settings page.

Debug log retention is separate: when a debug-enabled request log ages past the
``debug_log_retention_days`` window its verbose fields (headers, body) are
stripped, leaving only the lightweight summary row.  If
``debug_log_retention_days`` is 0 the debug detail is kept forever.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select, update

from voidswitch.core.audit import (
    SYSTEM_ACTOR_NAME,
    SYSTEM_ACTOR_SUB,
    AuditAction,
    AuditScope,
    record_audit,
)
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.models.db import AuditLog, RequestLog, SessionSpan, UsageDaily
from voidswitch.services import settings_store

log = get_logger("tasks.log_cleanup")


async def run_log_cleanup() -> None:
    """Periodic-task entry point: apply retention, discard the counts."""
    await cleanup_logs()


async def cleanup_logs() -> dict[str, int]:
    """Apply the configured retention windows now. Returns the affected counts.

    Used both by the periodic task and the dashboard's "clean now" action.
    """
    db = get_database()
    audit_days = settings_store.get_int("audit_log_retention_days", 0)
    request_days = settings_store.get_int("request_log_retention_days", 0)
    debug_days = settings_store.get_int("debug_log_retention_days", 0)
    heatmap_days = settings_store.get_int("heatmap_retention_days", 0)
    empty = {
        "deleted_request_logs": 0,
        "deleted_audit_logs": 0,
        "stripped_debug_logs": 0,
        "deleted_heatmap_days": 0,
        "deleted_session_spans": 0,
    }
    if audit_days <= 0 and request_days <= 0 and debug_days <= 0 and heatmap_days <= 0:
        return empty  # nothing to do — retention disabled for all

    now = dt.datetime.now(dt.UTC)
    async with db.session() as session:
        deleted_requests = 0
        deleted_audits = 0
        stripped_debug = 0
        deleted_heatmap = 0
        deleted_spans = 0

        if request_days > 0:
            cutoff = now - dt.timedelta(days=request_days)
            deleted_requests = await _delete_batched(session, RequestLog, RequestLog.ts < cutoff)

        if audit_days > 0:
            cutoff = now - dt.timedelta(days=audit_days)
            # The cleanup entry we're about to write has ts=now, so it never
            # falls inside this ts < cutoff window.
            deleted_audits = await _delete_batched(session, AuditLog, AuditLog.ts < cutoff)

        if debug_days > 0:
            cutoff = now - dt.timedelta(days=debug_days)
            stripped_debug = await _strip_debug_batched(session, cutoff)

        if heatmap_days > 0:
            cutoff = now - dt.timedelta(days=heatmap_days)
            cutoff_day = cutoff.strftime("%Y-%m-%d")
            deleted_heatmap = await _delete_batched(
                session, UsageDaily, UsageDaily.day < cutoff_day
            )
            deleted_spans = await _delete_batched(
                session, SessionSpan, SessionSpan.last_at < cutoff
            )

        if deleted_requests or deleted_audits or stripped_debug or deleted_heatmap or deleted_spans:
            log.info(
                "log_cleanup",
                deleted_requests=deleted_requests,
                deleted_audits=deleted_audits,
                stripped_debug=stripped_debug,
                deleted_heatmap_days=deleted_heatmap,
                deleted_session_spans=deleted_spans,
            )
            await record_audit(
                session,
                action=AuditAction.LOGS_CLEANUP,
                actor_sub=SYSTEM_ACTOR_SUB,
                actor_name=SYSTEM_ACTOR_NAME,
                target_type="logs",
                detail={
                    "deleted_request_logs": deleted_requests,
                    "deleted_audit_logs": deleted_audits,
                    "stripped_debug_logs": stripped_debug,
                    "deleted_heatmap_days": deleted_heatmap,
                    "deleted_session_spans": deleted_spans,
                    "audit_log_retention_days": audit_days,
                    "request_log_retention_days": request_days,
                    "debug_log_retention_days": debug_days,
                    "heatmap_retention_days": heatmap_days,
                },
                scope=AuditScope.SYSTEM.value,
            )

        return {
            "deleted_request_logs": deleted_requests,
            "deleted_audit_logs": deleted_audits,
            "stripped_debug_logs": stripped_debug,
            "deleted_heatmap_days": deleted_heatmap,
            "deleted_session_spans": deleted_spans,
        }


# Rows removed per statement. Bounding each DELETE keeps the transaction/journal
# small and avoids holding a long write lock (SQLite) or bloating a single
# transaction (Postgres) when a retention window first activates on a large table.
_CLEANUP_BATCH = 5000


async def _delete_batched(session, model, where_clause) -> int:
    """Delete rows matching ``where_clause`` in bounded batches; return the total.

    Uses ``DELETE ... WHERE id IN (SELECT id ... LIMIT n)`` and reads
    ``rowcount`` instead of a separate ``COUNT(*)`` scan. Commits between batches
    so a large purge never accumulates into one oversized transaction.
    """
    total = 0
    while True:
        subquery = select(model.id).where(where_clause).limit(_CLEANUP_BATCH)
        result = await session.execute(delete(model).where(model.id.in_(subquery)))
        removed = result.rowcount or 0
        total += removed
        if removed:
            await session.commit()
        if removed < _CLEANUP_BATCH:
            return total


async def _strip_debug_batched(session, cutoff: dt.datetime) -> int:
    """Strip verbose debug fields off aged rows in bounded batches; return the total.

    Self-terminating: each batch clears ``debug`` so those rows drop out of the
    ``debug IS TRUE`` filter on the next pass.
    """
    total = 0
    while True:
        subquery = (
            select(RequestLog.id)
            .where(RequestLog.ts < cutoff, RequestLog.debug.is_(True))
            .limit(_CLEANUP_BATCH)
        )
        result = await session.execute(
            update(RequestLog)
            .where(RequestLog.id.in_(subquery))
            .values(
                debug=False,
                req_headers=None,
                req_body=None,
                resp_headers=None,
                resp_body=None,
                debug_attempts=None,
                upstream_url=None,
                proxy_url=None,
            )
        )
        removed = result.rowcount or 0
        total += removed
        if removed:
            await session.commit()
        if removed < _CLEANUP_BATCH:
            return total
