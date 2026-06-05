"""Admin: audit log and request/usage log browsing."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import record_audit
from voidswitch.core.auth import (
    actor_display_name,
    get_current_user,
    is_staff,
    require_owner,
    require_staff,
)
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.security import decrypt_secret
from voidswitch.models.db import AuditLog, RequestLog, User, VoidToken
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
    items: list[AuditLogOut] = []
    for r in rows:
        out = AuditLogOut.model_validate(r)
        out.has_sensitive = bool(r.sensitive_ciphertext)
        items.append(out)
    return Page[AuditLogOut](
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post("/audit/{audit_id}/reveal")
async def reveal_audit_sensitive(
    audit_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
    actor: User = Depends(require_owner),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """Owner-only: decrypt and return the sensitive payload for one audit entry.

    Guarded behind a secondary confirmation in the UI. The reveal itself is
    audited (without re-storing the secret) so there is a trail of who looked.
    """
    entry = await session.get(AuditLog, audit_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Audit entry not found.")
    if not entry.sensitive_ciphertext:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No sensitive data for this entry.")
    try:
        payload = json.loads(
            decrypt_secret(entry.sensitive_ciphertext, secret=settings.server.secret_key)
        )
    except (ValueError, TypeError) as exc:  # pragma: no cover - corrupt/rotated key
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not decrypt sensitive data."
        ) from exc
    await record_audit(
        session,
        action="audit.reveal",
        actor_sub=actor.sub,
        actor_name=actor_display_name(actor),
        target_type="audit",
        target_id=audit_id,
        detail={"revealed_action": entry.action},
        ip=request.client.host if request.client else None,
    )
    return {"id": audit_id, "action": entry.action, "sensitive": payload}


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

    # Resolve human-friendly caller + token labels in two batched queries.
    token_ids = {r.token_id for r in rows if r.token_id is not None}
    subs = {r.user_sub for r in rows if r.user_sub}
    token_names: dict[int, str] = {}
    if token_ids:
        for tid, tname in (
            await session.execute(
                select(VoidToken.id, VoidToken.name).where(VoidToken.id.in_(token_ids))
            )
        ).all():
            token_names[tid] = tname
    user_names: dict[str, str | None] = {}
    if subs:
        for u in (
            (await session.execute(select(User).where(User.sub.in_(subs)))).scalars().all()
        ):
            user_names[u.sub] = u.name or u.username or u.email

    items: list[RequestLogOut] = []
    for r in rows:
        out = RequestLogOut.model_validate(r)
        if r.token_id is not None:
            out.token_name = token_names.get(r.token_id)
        if r.user_sub:
            out.user_name = user_names.get(r.user_sub)
        items.append(out)
    return Page[RequestLogOut](
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )
