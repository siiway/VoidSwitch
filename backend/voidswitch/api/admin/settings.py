"""Admin: runtime operational settings (thresholds, intervals)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, AuditScope, record_audit
from voidswitch.core.auth import actor_display_name, require_owner, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import User
from voidswitch.models.schemas import SettingsOut, SettingsUpdate
from voidswitch.services import settings_store
from voidswitch.tasks.log_cleanup import cleanup_logs

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
    # System settings are owner-tier only: admins may view (GET) but not edit.
    user: User = Depends(require_owner),
) -> SettingsOut:
    old_values = await settings_store.get_all(session)
    values = await settings_store.update(session, body.values)
    # Only record the settings that actually changed.
    changes = {}
    for k, v in body.values.items():
        if old_values.get(k) != v:
            changes[k] = v
    if changes:
        await record_audit(
            session,
            action=AuditAction.SETTINGS_UPDATE,
            actor_sub=user.sub,
            actor_name=actor_display_name(user),
            target_type="settings",
            detail={"changes": changes},
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SettingsOut(values=values)


@router.post("/clean-logs")
async def clean_logs_now(
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_owner),
) -> dict[str, int]:
    """Run log retention cleanup immediately (owner-only, destructive).

    Applies the configured retention windows right now instead of waiting for the
    background task. Returns the number of rows deleted / debug-stripped.
    """
    result = await cleanup_logs()
    await record_audit(
        session,
        action=AuditAction.LOGS_CLEANUP,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        target_type="logs",
        detail={"manual": True, **result},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        scope=AuditScope.ADMIN.value,
    )
    return result
