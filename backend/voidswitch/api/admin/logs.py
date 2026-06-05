"""Admin: audit log and request/usage log browsing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.auth import get_current_user, is_staff, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import AuditLog, RequestLog, User
from voidswitch.models.schemas import AuditLogOut, Page, RequestLogOut

router = APIRouter(prefix="/api/admin/logs", tags=["admin:logs"])


@router.get("/audit", response_model=Page[AuditLogOut])
async def audit_logs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> Page[AuditLogOut]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    count_stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return Page[AuditLogOut](
        items=[AuditLogOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/requests", response_model=Page[RequestLogOut])
async def request_logs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    success: bool | None = None,
    model: str | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> Page[RequestLogOut]:
    stmt = select(RequestLog).order_by(RequestLog.id.desc())
    count_stmt = select(func.count(RequestLog.id))
    if not is_staff(user):
        # Members may browse the request log, but only their own traffic.
        stmt = stmt.where(RequestLog.user_sub == user.sub)
        count_stmt = count_stmt.where(RequestLog.user_sub == user.sub)
    if success is not None:
        stmt = stmt.where(RequestLog.success.is_(success))
        count_stmt = count_stmt.where(RequestLog.success.is_(success))
    if model:
        stmt = stmt.where(RequestLog.model == model)
        count_stmt = count_stmt.where(RequestLog.model == model)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return Page[RequestLogOut](
        items=[RequestLogOut.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )
