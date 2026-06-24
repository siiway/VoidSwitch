"""Admin: runtime operational settings (thresholds, intervals)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, record_audit
from voidswitch.core.auth import actor_display_name, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import User
from voidswitch.models.schemas import SettingsOut, SettingsUpdate
from voidswitch.services import settings_store

router = APIRouter(prefix="/api/admin/settings", tags=["admin:settings"])


@router.get("", response_model=SettingsOut)
async def get_settings_values(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_staff),
) -> SettingsOut:
    values = await settings_store.get_all(session)
    return SettingsOut(values=values)


@router.put("", response_model=SettingsOut)
async def update_settings_values(
    body: SettingsUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_staff),
) -> SettingsOut:
    values = await settings_store.update(session, body.values)
    await record_audit(
        session,
        action=AuditAction.SETTINGS_UPDATE,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="settings",
        detail={"changes": body.values},
        ip=request.client.host if request.client else None,
    )
    return SettingsOut(values=values)
