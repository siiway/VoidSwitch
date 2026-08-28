"""OAuth login/callback and session endpoints."""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voidswitch import __version__
from voidswitch.core import auth
from voidswitch.core.audit import AuditAction, AuditScope, record_audit
from voidswitch.core.auth import actor_display_name
from voidswitch.core.config import Settings, get_settings
from voidswitch.core.database import get_session
from voidswitch.core.logging import get_logger
from voidswitch.core.security import create_session_token, hash_token
from voidswitch.core.version import commit_id
from voidswitch.models.db import User
from voidswitch.models.schemas import LoginStart, LoginTokenIn, SessionOut, UserOut
from voidswitch.services import settings_store

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = get_logger("api.auth")


def _session_out(
    user: User,
    settings: Settings,
    identity: auth.PrismIdentity | None = None,
) -> SessionOut:
    """Mint a dashboard session JWT with a computed lifetime.

    Precedence for the TTL (minutes):
    1. the runtime ``session_ttl_minutes`` setting, when set to >= 60;
    2. else the ``expires_in`` Prism returned at login (``identity``), when the
       caller is a Prism OAuth callback and Prism sent one;
    3. else the server config's ``session_ttl_minutes`` (existing default).
    """
    configured = settings_store.get_int("session_ttl_minutes", 0)
    if configured >= 60:
        ttl = configured
    elif identity is not None and identity.expires_in_seconds:
        ttl = max(60, identity.expires_in_seconds // 60)
    else:
        ttl = settings.server.session_ttl_minutes
    ttl = max(ttl, 1)
    token = create_session_token(
        secret=settings.server.secret_key,
        subject=user.sub,
        extra={"role": user.role, "name": user.name, "epoch": user.session_epoch},
        ttl_minutes=ttl,
    )
    return SessionOut(access_token=token, expires_in=ttl * 60, user=UserOut.model_validate(user))


@router.get("/config")
async def auth_config(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    configured = bool(settings.prism.client_id and "your-prism" not in settings.prism.client_id)
    return {
        "configured": configured,
        "version": __version__,
        "commit": commit_id(),
        "dev_mode": settings.server.dev_mode,
        "issuer": settings.prism.issuer,
        "login_url": f"{settings.server.base_url.rstrip('/')}/api/auth/login?redirect=1",
        # Non-secret OpenCode model defaults, surfaced so the (member-facing)
        # "My API Key" page can render an accurate install snippet without
        # hitting the staff-only settings endpoint. These are already public via
        # the /install script.
        "opencode_default_model": settings_store.get_str(
            "opencode_default_model", "claude-opus-4-8"
        ),
        "opencode_small_model": settings_store.get_str("opencode_small_model", ""),
        # Non-secret: drives the Logs tables' page size. Exposed here (not the
        # staff-only settings endpoint) so members can browse their own logs with
        # the same pagination.
        "logs_page_size": settings_store.get_int("logs_page_size", 50),
        # Non-secret: lets the dashboard shell hide the Proxies tab when proxy
        # switching is turned off (an external proxy handles egress).
        "proxy_switching_enabled": settings_store.get_bool("proxy_switching_enabled", True),
        # Non-secret: how many announcements the dashboard home panel shows inline
        # before the "view all" action reveals the rest.
        "announcements_home_count": settings_store.get_int("announcements_home_count", 3),
    }


@router.post("/dev-login", response_model=SessionOut)
async def dev_login(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    """No-OAuth sign-in for local development. Mints an owner session.

    Disabled unless ``server.dev_mode`` (VOIDSWITCH_SERVER__DEV_MODE=true).
    """
    if not settings.server.dev_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    user = await auth.dev_login_user(session, settings)
    await record_audit(
        session,
        action=AuditAction.AUTH_DEV_LOGIN,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    return _session_out(user, settings)


@router.post("/token-login", response_model=SessionOut)
async def token_login(
    body: LoginTokenIn,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    raw = body.token.strip()
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login token.")
    user = (
        await session.execute(select(User).where(User.login_token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if user is None or not user.enabled or not auth.is_staff(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid login token.")
    user.last_login_at = dt.datetime.now(dt.UTC)
    # Record the login-token sign-in explicitly — a distinct action plus the
    # login method + client, so it's clear in the audit trail that this session
    # was established with a login token rather than an interactive Prism login.
    await record_audit(
        session,
        action=AuditAction.AUTH_TOKEN_LOGIN,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        detail={"method": "login_token", "token_prefix": user.login_token_prefix},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        scope=AuditScope.SELF.value,
    )
    return _session_out(user, settings)


@router.get("/login", response_model=None)
async def login(
    redirect: int = 0, settings: Settings = Depends(get_settings)
) -> LoginStart | RedirectResponse:
    authorize_url, state = auth.build_authorize_url(settings)
    if redirect:
        return RedirectResponse(authorize_url, status_code=302)
    return LoginStart(authorize_url=authorize_url, state=state)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    frontend = settings.server.frontend_url.rstrip("/")
    target = f"{frontend}/login/callback"

    if error or not code or not state:
        params = urlencode({"error": error or "missing_code"})
        return RedirectResponse(f"{target}#{params}", status_code=302)

    try:
        identity = await auth.exchange_code(settings, code, state)
        user = await auth.upsert_user(session, settings, identity)
        await record_audit(
            session,
            action=AuditAction.AUTH_LOGIN,
            actor_sub=user.sub,
            actor_name=actor_display_name(user),
            ip=request.client.host if request.client else None,
            scope=AuditScope.SELF.value,
        )
    except auth.LoginDenied as exc:
        log.info("oauth_callback_access_denied", error=str(exc))
        params = urlencode({"error": "access_denied"})
        return RedirectResponse(f"{target}#{params}", status_code=302)
    except Exception as exc:
        detail = getattr(exc, "detail", "") or str(exc) or repr(exc)
        request_url = None
        if isinstance(exc, httpx.HTTPError) and exc.request is not None:
            request_url = str(exc.request.url)
        log.warning(
            "oauth_callback_failed",
            type=type(exc).__name__,
            error=detail,
            detail=detail,
            cause=repr(exc.__cause__) if exc.__cause__ else None,
            request_url=request_url,
            exc_info=True,
        )
        params = urlencode({"error": "login_failed"})
        return RedirectResponse(f"{target}#{params}", status_code=302)

    session_out = _session_out(user, settings, identity)
    params = urlencode(
        {"access_token": session_out.access_token, "expires_in": session_out.expires_in}
    )
    return RedirectResponse(f"{target}#{params}", status_code=302)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(auth.get_current_user)) -> User:
    return user


@router.post("/logout")
async def logout(
    request: Request,
    user: User = Depends(auth.get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    # Stateless JWTs: the client discards the token. Endpoint exists for symmetry,
    # and to leave a trail of who signed out and when.
    await record_audit(
        session,
        action=AuditAction.AUTH_LOGOUT,
        actor_sub=user.sub,
        actor_name=actor_display_name(user),
        ip=request.client.host if request.client else None,
        scope=AuditScope.SELF.value,
    )
    return {"ok": True}
