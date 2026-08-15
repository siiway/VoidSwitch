"""Admin: runtime operational settings (thresholds, intervals)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch.core.audit import AuditAction, AuditScope, record_audit
from voidswitch.core.auth import actor_display_name, require_owner, require_staff
from voidswitch.core.database import get_session
from voidswitch.models.db import User
from voidswitch.models.schemas import SettingsOut, SettingsUpdate
from voidswitch.services import settings_store
from voidswitch.tasks.log_cleanup import cleanup_logs

router = APIRouter(prefix="/api/admin/settings", tags=["admin:settings"])

# The operation rate limit gates mutating dashboard actions for everyone (owners
# included). Refuse to save a value so restrictive it could lock the dashboard —
# it must always permit at least this many operations per minute so an owner can
# still change settings back.
MIN_OPERATION_RATE_PER_MINUTE = 20

# The heatmap rollups (and their statistics) must be retainable for at least a
# year, so any non-"keep forever" retention window is required to be >= this.
MIN_HEATMAP_RETENTION_DAYS = 365

# A custom dashboard session duration must be at least this many minutes
# (0 / empty is allowed: it means "follow what Prism returns at login").
MIN_SESSION_TTL_MINUTES = 60


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _validate_operation_rate_limit(effective: dict[str, object]) -> None:
    window = _to_int(effective.get("operation_rate_limit_window_seconds"), 0)
    max_requests = _to_int(effective.get("operation_rate_limit_max_requests"), 0)
    # 0 max / 0 window = disabled → always fine.
    if max_requests <= 0 or window <= 0:
        return
    per_minute = max_requests * 60 / window
    if per_minute < MIN_OPERATION_RATE_PER_MINUTE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Operation rate limit is too low: it must allow at least "
            f"{MIN_OPERATION_RATE_PER_MINUTE} operations per minute "
            f"(got {per_minute:.0f}/min from {max_requests} per {window}s), "
            "otherwise an owner could lock everyone out of the dashboard.",
        )


def _validate_heatmap_retention(effective: dict[str, object]) -> None:
    days = _to_int(effective.get("heatmap_retention_days"), MIN_HEATMAP_RETENTION_DAYS)
    # 0 = keep forever → always fine; otherwise it must cover at least a year.
    if 0 < days < MIN_HEATMAP_RETENTION_DAYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Heatmap retention is too short: it must be 0 (keep forever) or at "
            f"least {MIN_HEATMAP_RETENTION_DAYS} days (got {days}).",
        )


def _validate_session_ttl(effective: dict[str, object]) -> None:
    minutes = _to_int(effective.get("session_ttl_minutes"), 0)
    # 0 = follow Prism's expires_in at login → always fine; otherwise it must be
    # at least an hour so sessions never silently expire mid-task.
    if 0 < minutes < MIN_SESSION_TTL_MINUTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Session duration is too short: it must be 0 (follow Prism) or at "
            f"least {MIN_SESSION_TTL_MINUTES} minutes (got {minutes}).",
        )


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
    # Guard against a self-inflicted lockout: validate the *effective* operation
    # rate limit (existing values overlaid with this update) before persisting.
    _validate_operation_rate_limit({**old_values, **body.values})
    _validate_heatmap_retention({**old_values, **body.values})
    _validate_session_ttl({**old_values, **body.values})
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


class StaticProxyTestRequest(BaseModel):
    url: str = ""
    probe_url: str = "https://api.openai.com/v1/models"


@router.post("/test-static-proxy")
async def test_static_proxy(
    body: StaticProxyTestRequest,
    _: User = Depends(require_staff),
) -> dict[str, object]:
    """Test a static proxy URL by making a lightweight probe request through it.

    Returns success/failure with latency and diagnostic detail — the same kind of
    probe the proxy resurrector uses, so an operator can validate a proxy URL
    before saving it.
    """
    proxy_url = body.url.strip()
    probe_url = body.probe_url.strip() or "https://api.openai.com/v1/models"
    if not proxy_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Proxy URL is required.")
    try:
        proxy = httpx.Proxy(proxy_url)
        transport = httpx.AsyncHTTPTransport(proxy=proxy)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0),
            follow_redirects=False,
        ) as client:
            import time
            start = time.monotonic()
            r = await client.get(probe_url)
            latency_ms = (time.monotonic() - start) * 1000.0
            return {
                "ok": True,
                "status_code": r.status_code,
                "latency_ms": round(latency_ms, 1),
                "error": None,
            }
    except httpx.ProxyError as exc:
        return {"ok": False, "status_code": None, "latency_ms": None,
                "error": f"Proxy error: {exc}"}
    except httpx.ConnectError as exc:
        return {"ok": False, "status_code": None, "latency_ms": None,
                "error": f"Connect error: {exc}"}
    except httpx.TimeoutException as exc:
        return {"ok": False, "status_code": None, "latency_ms": None,
                "error": f"Timeout: {exc}"}
    except Exception as exc:
        return {"ok": False, "status_code": None, "latency_ms": None,
                "error": f"{type(exc).__name__}: {exc}"}
