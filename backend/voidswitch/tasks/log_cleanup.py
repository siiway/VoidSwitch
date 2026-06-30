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

from sqlalchemy import delete, func, select, update

from voidswitch.core.audit import (
    SYSTEM_ACTOR_NAME,
    SYSTEM_ACTOR_SUB,
    AuditAction,
    AuditScope,
    record_audit,
)
from voidswitch.core.database import get_database
from voidswitch.core.logging import get_logger
from voidswitch.models.db import AuditLog, RequestLog
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
    empty = {"deleted_request_logs": 0, "deleted_audit_logs": 0, "stripped_debug_logs": 0}
    if audit_days <= 0 and request_days <= 0 and debug_days <= 0:
        return empty  # nothing to do — retention disabled for all

    now = dt.datetime.now(dt.UTC)
    async with db.session() as session:
        deleted_requests = 0
        deleted_audits = 0
        stripped_debug = 0

        if request_days > 0:
            cutoff = now - dt.timedelta(days=request_days)
            deleted_requests = await _count_older(session, RequestLog, RequestLog.ts, cutoff)
            if deleted_requests:
                await session.execute(delete(RequestLog).where(RequestLog.ts < cutoff))

        if audit_days > 0:
            cutoff = now - dt.timedelta(days=audit_days)
            # Don't count/delete the cleanup entry we're about to write.
            deleted_audits = await _count_older(session, AuditLog, AuditLog.ts, cutoff)
            if deleted_audits:
                await session.execute(delete(AuditLog).where(AuditLog.ts < cutoff))

        if debug_days > 0:
            cutoff = now - dt.timedelta(days=debug_days)
            stripped_debug = await _count_debug_older(session, cutoff)
            if stripped_debug:
                await session.execute(
                    update(RequestLog)
                    .where(RequestLog.ts < cutoff, RequestLog.debug.is_(True))
                    .values(
                        debug=False,
                        req_headers=None,
                        req_body=None,
                        resp_headers=None,
                        resp_body=None,
                        upstream_url=None,
                        proxy_url=None,
                    )
                )

        if deleted_requests or deleted_audits or stripped_debug:
            log.info(
                "log_cleanup",
                deleted_requests=deleted_requests,
                deleted_audits=deleted_audits,
                stripped_debug=stripped_debug,
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
                    "audit_log_retention_days": audit_days,
                    "request_log_retention_days": request_days,
                    "debug_log_retention_days": debug_days,
                },
                scope=AuditScope.SYSTEM.value,
            )

        return {
            "deleted_request_logs": deleted_requests,
            "deleted_audit_logs": deleted_audits,
            "stripped_debug_logs": stripped_debug,
        }


async def _count_older(session, model, ts_column, cutoff: dt.datetime) -> int:
    return int(
        (await session.execute(select(func.count(model.id)).where(ts_column < cutoff))).scalar_one()
        or 0
    )


async def _count_debug_older(session, cutoff: dt.datetime) -> int:
    return int(
        (
            await session.execute(
                select(func.count(RequestLog.id)).where(
                    RequestLog.ts < cutoff, RequestLog.debug.is_(True)
                )
            )
        ).scalar_one()
        or 0
    )
