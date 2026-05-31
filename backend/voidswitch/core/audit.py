"""Audit logging helper."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.models.db import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_sub: str | None = None,
    actor_name: str | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """Append an administrative audit entry. Caller owns the transaction."""
    session.add(
        AuditLog(
            action=action,
            actor_sub=actor_sub,
            actor_name=actor_name,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail or {},
            ip=ip,
        )
    )
